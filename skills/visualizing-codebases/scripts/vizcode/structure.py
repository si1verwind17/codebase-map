"""Structure pass: committed tree -> structure.json (nodes, uses-code relations, per-file facts)."""
from __future__ import annotations

import fnmatch
import posixpath
import re
import tempfile
import time
from pathlib import Path

from . import SCANNER_VERSION, SCHEMA_VERSION, facts, gitsrc, ids, proto, readme, routes, stack, typelinks
from .adapters import generic
from .adapters import python as py_adapter
from .adapters import scala as scala_adapter
from .adapters import decode
from .adapters.langs import ALL, BY_SUFFIX, SPECS
from .modules import detect_modules, names_from_build_files, path_aliases

# Scala and Python keep their own adapters; every language in adapters/langs.py goes through the generic walker
LANGS = {".py": ("python", py_adapter), ".scala": ("scala", scala_adapter),
         **{suf: (spec.lang, generic.Adapter(spec)) for suf, spec in BY_SUFFIX.items()}}
MAX_BYTES = 512 * 1024
# matched against the whole path
DEFAULT_EXCLUDES = [
    "*/test/*", "test/*", "*/tests/*", "tests/*", "*/__tests__/*", "*/src/test/*",
    "docs/*", ".*/*", "*/.*/*", "*/node_modules/*", "*/.venv/*", ".venv/*", "*/venv/*", "venv/*",
    "*/site-packages/*", "*/target/*", "target/*",
]
# build output, generated files and Gradle build scripts, matched against the whole path of a file in a language
# of adapters/langs.py only: Python and Scala keep DEFAULT_EXCLUDES alone, so their maps do not change
BUILD_EXCLUDES = [p for d in ("dist", "build", "out", "bin", "obj", "vendor", ".gradle", ".next", "coverage")
                  for p in (f"*/{d}/*", f"{d}/*")] + ["node_modules/*", "*.min.js", "*.d.ts", "*.pb.go", "*_pb.ts",
                                                      "*.gradle.kts"]
# Cargo's extra binaries (`src/bin/*.rs`) are source, not build output
BIN_EXCLUDES = ("*/bin/*", "bin/*")
# matched against the file name only; a table's test glob with a folder in it is matched against the path
TEST_FILES = ["test_*.py", "*_test.py", "conftest.py", "*Spec.scala", "*Test.scala", "*Suite.scala",
              *dict.fromkeys(t for spec in BY_SUFFIX.values() for t in spec.tests if "/" not in t)]
# EF Core's generated migration files: each holds a full copy of the model (`ToTable` of every table)
EF_MIGRATIONS = [p for g in ("Migrations/*.Designer.cs", "Migrations/*ModelSnapshot.cs") for p in (g, "*/" + g)]
GENERIC_EXCLUDES = {suf: BUILD_EXCLUDES + [p for t in spec.tests if "/" in t for p in (t, "*/" + t)]
                    + (EF_MIGRATIONS if suf == ".cs" else []) for suf, spec in BY_SUFFIX.items()}
SBT_BUILD_DIR = "project/*"  # sbt build definitions, excluded only when build.sbt exists


def excluded(path: str, patterns: list[str]) -> bool:
    name = path.rsplit("/", 1)[-1]
    extra = GENERIC_EXCLUDES.get(Path(path).suffix, [])
    if path.endswith(".rs") and (path.startswith("src/bin/") or "/src/bin/" in path):
        extra = [p for p in extra if p not in BIN_EXCLUDES]
    patterns = patterns + extra
    return any(fnmatch.fnmatch(path, p) for p in patterns) or any(fnmatch.fnmatch(name, p) for p in TEST_FILES)


# languages that resolve imports against one another's names: Python and Scala always have; Java, Kotlin and
# Scala import one another's packages, but not Python's folder and file names; TypeScript and JavaScript import
# each other. Any other language has its own
NAME_SCOPES = {"python": "jvm", "scala": "jvm", "java": "java", "kotlin": "java",
               "typescript": "js", "javascript": "js"}
# the other scope a language's names are also written to
ALSO_SCOPE = {"scala": "java", "java": "jvm", "kotlin": "jvm"}
# languages whose declared package (namespace) is what other files import; the others import paths
DECLARED = ("python", "scala", "java", "kotlin", "csharp", "php")


def _scope(lang: str) -> str:
    return NAME_SCOPES.get(lang, lang)


def _scopes(lang: str) -> list[str]:
    """Every scope a name of the language is seen in."""
    return [_scope(lang)] + ([ALSO_SCOPE[lang]] if lang in ALSO_SCOPE else [])


def _lang(f: str) -> str:
    return LANGS[Path(f).suffix][0]


def _declared_package(f: str, r: dict, module: dict) -> str | None:
    """The package a file declares, when its language imports by package; a folder package (PHP without a
    namespace) is none."""
    lang, pkg = _lang(f), r["package"]
    if not pkg or pkg == "_root_" or lang not in DECLARED:
        return None
    return None if lang in SPECS and pkg == generic._folder(f, module) else pkg


def _ruby_lib_names(f: str) -> list[str]:
    """What `require` names a file under a `lib/` folder by: `lib/core/order.rb` -> core/order, core."""
    parts = f.removesuffix(".rb").split("/")
    if "lib" not in parts[:-1]:
        return []
    rest = parts[len(parts) - parts[::-1].index("lib"):]
    return ["/".join(rest[:i]) for i in range(len(rest), 0, -1)]


def _module_names(modules: list[dict], results: dict[str, dict], file_mod: dict[str, str],
                  build_names: dict[str, str]) -> dict[str, dict[str, str]]:
    """Name scope (NAME_SCOPES) -> importable name prefix -> module id, used to resolve imports to modules."""
    names: dict[str, dict[str, str]] = {"jvm": {}}
    mod_by_id = {m["id"]: m for m in modules}
    for m in modules:
        if m["lang"] == "python" and m["build"] == "python-package":
            names["jvm"][m["path"].replace("/", ".")] = m["id"]
            names["jvm"][Path(m["path"]).name] = m["id"]
    for f, r in results.items():
        if not f.endswith(".py") and (pkg := _declared_package(f, r, mod_by_id[file_mod[f]])):
            for scope in _scopes(_lang(f)):
                names.setdefault(scope, {}).setdefault(pkg, file_mod[f])
        if f.endswith(".rb"):
            for n in _ruby_lib_names(f):
                names.setdefault("ruby", {}).setdefault(n, file_mod[f])
    for mid, name in sorted(build_names.items()):
        for scope in _scopes(mod_by_id[mid]["lang"]):
            names.setdefault(scope, {}).setdefault(name, mid)
    return names


def _resolve_import(target: str, names: dict[str, str], sep: str = ".") -> str | None:
    """The module of the longest name the target is or sits under (Go: the longest module path, as `go` does)."""
    best = None
    for prefix, mid in names.items():
        if target == prefix or target.startswith(prefix + sep):
            if best is None or len(prefix) > len(best[0]):
                best = (prefix, mid)
    return best[1] if best else None


def _relative_file(f: str, target: str, files: dict[str, dict]) -> str | None:
    """The scanned file a relative import names (`./x`, `../y/index`, Ruby `require_relative "z"`): as written,
    with a source suffix of the language's name scope, or the folder's `index` file."""
    lang = _lang(f)
    if lang not in SPECS:
        return None
    sufs = [s for spec in ALL if _scope(spec.lang) == _scope(lang) for s in spec.suffixes]
    base = posixpath.normpath(posixpath.join(posixpath.dirname(f), target))
    stem = next((base[:-len(s)] for s in sufs if base.endswith(s)), base)     # `./x.js` written for x.ts
    return next((c for c in [base, *(stem + s for s in sufs), *(f"{stem}/index{s}" for s in sufs)] if c in files), None)


def _internal(results: dict[str, dict], file_mod: dict[str, str], mod_by_id: dict[str, dict],
              names: dict[str, dict[str, str]], protos: list[dict], aliases: set[str]) -> dict[str, set[str]]:
    """Language -> import prefixes that name the repo's own code: packages, Python dotted names, module names,
    tsconfig path aliases, Rust `mod` names."""
    scopes: dict[str, set[str]] = {scope: set(n) for scope, n in names.items()}
    jvm = scopes.setdefault("jvm", set())
    for f, r in results.items():
        if pkg := _declared_package(f, r, mod_by_id[file_mod[f]]):
            for scope in _scopes(_lang(f)):
                scopes.setdefault(scope, set()).add(pkg)
        if f.endswith(".py"):
            jvm.add(py_adapter.dotted_names(mod_by_id[file_mod[f]], f)[0])
            jvm.add(Path(f).stem)
            jvm.update(Path(f).parent.parts)
        if f.endswith(".rs"):
            scopes.setdefault("rust", set()).update(i["target"] for i in r["imports"]
                                                    if i["relative"] and "::" not in i["target"])
    for p in protos:
        stem = Path(p["file"]).stem
        jvm.update((f"{stem}_pb2", f"{stem}_pb2_grpc"))
    scopes.setdefault("js", set()).update(aliases)
    for out in scopes.values():
        out.discard("")
    return {lang: scopes.get(_scope(lang), set()) for lang in {_lang(f) for f in results}}


# languages whose classes may extend each other's; any other language links only within itself
FAMILIES = {"java": "jvm", "kotlin": "jvm", "scala": "jvm", "typescript": "js", "javascript": "js"}


def _family(lang: str) -> str:
    return FAMILIES.get(lang, lang)


def _attach(nodes: list[dict], results: dict[str, dict]) -> None:
    """Methods a file attached to a type it does not declare (Go receivers, Rust `impl`): counted on that type's
    class node, made from the first such file when no file declares the type."""
    by_id = {n["id"]: n for n in nodes}
    for r in results.values():
        for a in r.get("attached", []):
            if a["id"] in by_id:
                by_id[a["id"]]["metrics"]["methods"] += a["metrics"]["methods"]
            else:
                by_id[a["id"]] = {**a, "metrics": dict(a["metrics"])}
                nodes.append(by_id[a["id"]])


def _implements(nodes: list[dict], results: dict[str, dict], file_mod: dict[str, str]) -> None:
    """Set `implements` on classes from the names they extend: the nearest class or trait of that name in the
    same language family (same package, then same module, then anywhere); objects cannot be extended."""
    by_id = {n["id"]: n for n in nodes}
    named: dict[str, list[dict]] = {}
    for n in nodes:
        if n["kind"] == "class" and not n["id"].endswith("$") and not n["name"].startswith("new "):
            named.setdefault(n["name"], []).append(n)
    for f, r in results.items():
        for cid, supers in r.get("supers", []):
            me, out = by_id[cid], []
            for raw in supers:
                cands = [c for c in named.get(re.split(r"[.\\:]+", raw)[-1], [])
                         if c["id"] != cid and _family(c["lang"]) == _family(me["lang"])]
                if "." in raw:
                    cands = [c for c in cands if c["id"].endswith("." + raw) or c["id"].endswith("::" + raw)]
                pkg = me["id"].split("::", 1)[0]
                for level in (lambda c: c["file"].rsplit("/", 1)[0] == me["file"].rsplit("/", 1)[0],
                              lambda c: c["id"].split("::", 1)[0] == pkg, lambda c: True):
                    hit = [c for c in cands if level(c)]
                    if hit:
                        if len(hit) == 1:
                            out.append(hit[0]["id"])
                        break
            if out:
                me["implements"] = out


def _grpc_ends(r: dict, keys: dict[str, list[str]]) -> list[dict]:
    """gRPC client stubs and server implementations in one file, with the proto keys of their service."""
    by_id = {n["id"]: n for n in r["nodes"]}
    out = []
    for cid, bases in list(r.get("bases", [])) + list(r.get("supers", [])):
        for b in bases:
            if (svc := proto.base_end(b)) and (svc in keys or proto.generated(b)):
                out.append({"side": "server", "service": svc, "keys": keys.get(svc, []),
                            "in": cid, "line": by_id[cid]["line"]})
    for c in r["calls"]:
        if c.get("in") and (end := proto.call_end(c["callee"])) and (end[1] in keys or proto.generated(c["callee"])):
            out.append({"side": end[0], "service": end[1], "keys": keys.get(end[1], []),
                        "in": c["in"], "line": c["line"]})
    return sorted(out, key=lambda e: e["line"])


def _spans(r: dict, kind: str) -> list[tuple[int, int, str]]:
    return [(n["line"], n["line"] + n["metrics"]["loc"] - 1, n["id"]) for n in r["nodes"] if n["kind"] == kind]


# the handler (or table site) of a fact outside any method of a generic-walker file that has no file node yet:
# build creates the file node and puts its id in place (_file_node)
NEW_FILE_NODE = "\0file"


def _file_id(r: dict, module: dict, lang: str) -> str:
    """The file node; else, for Python and Scala (where file nodes exist only for top-level defs), the first class,
    else the package; for a generic-walker language NEW_FILE_NODE, never an unrelated class or the package."""
    kinds = {k: next((n["id"] for n in r["nodes"] if n["kind"] == k), None) for k in ("file", "class")}
    if not kinds["file"] and lang in SPECS:
        return NEW_FILE_NODE
    return kinds["file"] or kinds["class"] or ids.package_id(module["id"], r["package"])


def _file_node(r: dict, f: str, module_id: str, lang: str, loc: int, reg: ids.IdRegistry) -> None:
    """Create the file node of a generic-walker file whose route handler or table site is the file itself (an
    inline function, a file of no functions), as the walker creates it on a top-level function. Runs after
    _resolve_handlers: a route whose handler name resolves needs none."""
    facts = [x for x in (*r["routes"], *r["tables"]) if NEW_FILE_NODE in (x.get("handler"), x.get("in"))]
    if not facts:
        return
    pid, name = ids.package_id(module_id, r["package"]), Path(f).name
    node = {"id": reg.claim(f"{pid}{name}"), "kind": "file", "parent": pid, "name": name, "lang": lang, "file": f,
            "line": 1, "visibility": "public", "metrics": {"loc": loc, "methods": 0}}
    r["nodes"].append(node)
    for x in facts:
        for key in ("handler", "in"):
            if x.get(key) == NEW_FILE_NODE:
                x[key] = node["id"]


def _pattern_routes(st: stack.Stack, lang: str, data: bytes, r: dict, module: dict) -> list[dict]:
    """Route facts from the route patterns of the packs and stack.yaml. A regex route's handler is the method
    around the match; failing that, the file (_file_id). An annotated route's
    handler is the annotated method (the generic walker's recorded annotations)."""
    imports = stack.import_names(r["imports"], lang)
    found = stack.find_routes(st, lang, decode(data), imports, _spans(r, "method"), _file_id(r, module, lang)) \
        + stack.find_annotated(st, lang, r.get("annotations", []), r["nodes"], imports)
    return _dedupe(st.patterns, lang, found, "routes", "framework", ("method", "path", "handler"), r)


def _dedupe(pats: list, lang: str, found: list[dict], group: str, name: str, key: tuple[str, ...],
            r: dict) -> list[dict]:
    """Two patterns of one group giving the same fact (key fields; Spring and JAX-RS annotations on one method)
    give one, named after the pattern listed first in that group (packs, then stack.yaml); one pattern's own
    matches stay. Each dropped fact is noted in r["deduped"] as (group, its pattern, the kept pattern)."""
    order = {p.name: i for i, p in enumerate(x for x in pats if x.lang == lang)}
    first: dict[tuple, str] = {}
    for fact in found:
        k = tuple(fact[x] for x in key)
        if k not in first or order[fact[name]] < order[first[k]]:
            first[k] = fact[name]
    kept = []
    for fact in found:
        if (by := first[tuple(fact[x] for x in key)]) == fact[name]:
            kept.append(fact)
        else:
            r.setdefault("deduped", []).append((group, fact[name], by))
    return kept


def _resolve_handlers(results: dict[str, dict], file_mod: dict[str, str]) -> None:
    """Replace the span-rule handler of a route that names one (`handler_name`) with the method or function of
    that name (its last `.` or `::` segment: `h.GetOrder`, `handlers::get_order`): in the same file, else the same
    package, else the module. Ambiguity at a level, or no match, keeps the span rule's handler."""
    methods: dict[tuple[str, str], list[tuple[str, str, str]]] = {}   # (module, name) -> (file, package, id)
    for f, r in results.items():
        for n in r["nodes"]:
            if n["kind"] == "method":
                methods.setdefault((file_mod[f], n["name"]), []).append((f, r["package"], n["id"]))
    for f, r in results.items():
        for route in r["routes"]:
            name = route.pop("handler_name", None)
            if not name:
                continue
            cands = methods.get((file_mod[f], re.split(r"\.|::", name)[-1]), [])
            for level in (lambda c: c[0] == f, lambda c: c[1] == r["package"], lambda c: True):
                hit = [c for c in cands if level(c)]
                if len(hit) == 1:
                    route["handler"] = hit[0][2]
                if hit:
                    break


def _pattern_tables(st: stack.Stack, lang: str, data: bytes, r: dict, module: dict) -> list[dict]:
    """Table facts from the table patterns of the packs and stack.yaml. Two patterns giving the same (table,
    line, in) give one fact, named after the pattern listed first; one pattern's own matches stay. In a
    generic-walker language a class defines one table: when patterns name different tables defined on one class
    (JPA `@Entity(name = ...)` and `@Table(name = ...)`), the pattern listed first keeps its facts."""
    found = stack.find_tables(st, lang, decode(data), stack.import_names(r["imports"], lang),
                              _spans(r, "method"), _spans(r, "class"), _file_id(r, module, lang))
    kept = _dedupe(st.tables, lang, found, "tables", "pattern", ("table", "line", "in"), r)
    if lang not in SPECS:
        return kept
    order = {p.name: i for i, p in enumerate(x for x in st.tables if x.lang == lang)}
    first: dict[str, str] = {}
    for t in kept:
        if t["kind"] == "defined" and (t["in"] not in first or order[t["pattern"]] < order[first[t["in"]]]):
            first[t["in"]] = t["pattern"]
    out = []
    for t in kept:
        if t["kind"] == "defined" and first[t["in"]] != t["pattern"]:
            r.setdefault("deduped", []).append(("tables", t["pattern"], first[t["in"]]))
        else:
            out.append(t)
    return out


def _pattern_queues(st: stack.Stack, lang: str, data: bytes, r: dict, module: dict) -> list[dict]:
    """In-process queue creation sites from the queue patterns of the packs and stack.yaml, one per (line, in)."""
    found = stack.find_queues(st, lang, decode(data), stack.import_names(r["imports"], lang), _spans(r, "method"),
                              _file_id(r, module, lang))
    return _dedupe(st.queues, lang, found, "queues", "pattern", ("line", "in"), r)



def _packages_named(r: dict, head: str) -> set[str] | None:
    """The packages a file's `head` (an object it names) may come from: what imports it by name, else the file's
    own package and its wildcard imports. None (any package) for a fully qualified name (`acme.api.X`)."""
    if head[:1].islower():
        return None
    named, wild = set(), {r["package"]}
    for imp in r["imports"]:
        t, names = imp["target"], imp.get("names") or []
        if t.endswith("." + head) and not names:
            named.add(t[:-len(head) - 1])
        elif head in names or head in (imp.get("renames") or {}):
            named.add(t)
        elif not names and not t.rsplit(".", 1)[-1][:1].isupper():
            wild.add(t)
    return named or wild


def _tapir(results: dict[str, dict], file_mod: dict[str, str]) -> None:
    """Tapir endpoints: resolve val chains per module and find the endpoints built in method and val bodies, then
    place each where it is served. Bound to server logic (`X.endpoint.zServerLogic`, in any module): a route in the
    binding's body. Defined in a file that interprets endpoints as requests: a client. When the repo binds no
    endpoint at all, every other one is a route where it is defined, as before; when it does, an unbound endpoint is
    a client if a file using an sttp client names it, and otherwise a contract described here and drawn nowhere."""
    found = []
    for mid in sorted({file_mod[f] for f in results if f.endswith(".scala")}):
        vals = {}
        for f, r in results.items():
            if file_mod[f] == mid:
                vals.update(r["tapir"]["vals"])
        resolved = routes.resolve_tapir(vals)
        for f, r in results.items():
            if file_mod[f] != mid:
                continue
            known = {**resolved, routes.ROOT: []} if r["tapir"].get("root") else resolved
            if not known:
                continue
            for i, (fid, line, body) in enumerate(r["tapir"]["bodies"]):
                for method, path in routes.tapir_uses(body, known):
                    found.append({"file": f, "fid": fid, "line": line, "method": method, "path": path,
                                  "qual": r["tapir"].get("named", {}).get(i), "client": r["tapir"].get("client")})
    binds: dict[tuple[str, str, int], str] = {}   # (file, endpoint as written, line) -> innermost binding body
    for f, r in results.items():
        for fid, written, line in r["tapir"].get("binds", []) if f.endswith(".scala") else []:
            binds[(f, written, line)] = fid
    binders = {(f, fid) for (f, _, _), fid in binds.items()}
    mentions = [(f, m) for f, r in results.items() if f.endswith(".scala") for m in r["tapir"].get("mentions", [])]

    def names(e: dict, f: str, written: str) -> bool:
        """Does `written`, in file f, name endpoint e? A bare name only in e's own file; a dotted one by its tail,
        from a package file f can see it in."""
        if "." not in written:
            return f == e["file"] and e["qual"].rsplit(".", 1)[-1] == written
        if not (e["qual"] == written or e["qual"].endswith("." + written)):
            return False
        pkgs = _packages_named(results[f], written.split(".", 1)[0])
        return pkgs is None or results[e["file"]]["package"] in pkgs

    def bound(e: dict) -> list[tuple[str, str, int]]:
        if (e["file"], e["fid"]) in binders:   # built in the body that binds it (or rebound to it in its file)
            return [(e["file"], e["fid"], e["line"])]
        if e["qual"] is None:
            return []
        hits = [(f, fid, line) for (f, written, line), fid in binds.items() if names(e, f, written)]
        same = [h for h in hits if file_mod[h[0]] == file_mod[e["file"]]]
        return same or hits

    def called(e: dict) -> bool:
        """Named (`Orders.endpoint`, `Orders.endpoint.call(..)`) in a file that uses an sttp client."""
        if e["qual"] is None:
            return False
        parts = e["qual"].split(".")
        tails = [".".join(parts[k:]) for k in range(len(parts) - 1)]
        return any(names(e, f, t) for f, m in mentions for t in tails if m == t or m.startswith(t + "."))

    served = {id(e): bound(e) for e in found if not e["client"]}
    any_bound = any(served.values())
    for e in found:
        r = results[e["file"]]
        client = {"method": e["method"], "path": e["path"], "in": e["fid"], "line": e["line"],
                  "framework": "tapir-client"}
        if e["client"]:   # interpreted as a request: an outbound method + path, matched against routes
            r.setdefault("clients", []).append(client)
        elif served[id(e)]:
            for f, fid, line in served[id(e)]:
                results[f]["routes"].append({"method": e["method"], "path": e["path"], "handler": fid,
                                             "line": line, "framework": "tapir"})
        elif not any_bound:
            r["routes"].append({"method": e["method"], "path": e["path"], "handler": e["fid"],
                                "line": e["line"], "framework": "tapir"})
        elif called(e):
            r.setdefault("clients", []).append(client)


def build(repo: Path, out_dir: str | None = None, extra_excludes: list[str] | None = None) -> dict:
    t0 = time.time()
    repo = repo.resolve()
    commit = gitsrc.head_commit(repo)
    root_prefix = gitsrc.project_root(repo)
    if root_prefix:
        gitsrc.require_committed(repo, commit)
    st = stack.load(repo / out_dir / "stack.yaml" if out_dir else None)
    patterns = DEFAULT_EXCLUDES + (extra_excludes or []) + ([out_dir.rstrip("/") + "/*"] if out_dir else [])
    results: dict[str, dict] = {}
    texts: dict[str, str] = {}
    lines: dict[str, int] = {}     # a generic-walker file's line count, for a file node made after the scan
    skipped: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in gitsrc.export_tree(repo, commit, root):
            skipped.append({"file": name, "reason": "link points outside the repository; not extracted"})
        if (root / "build.sbt").exists():
            patterns.append(SBT_BUILD_DIR)
        files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                       if p.is_file() and not p.is_symlink() and p.suffix in LANGS)
        excluded_files = [f for f in files if excluded(f, patterns)]
        dropped = set(excluded_files)
        files = [f for f in files if f not in dropped]
        modules, file_mod, unassigned = detect_modules(root, files)
        mod_by_id = {m["id"]: m for m in modules}
        build_names, aliases = names_from_build_files(root, modules), path_aliases(root, modules)
        reg = ids.IdRegistry()
        for f in files:
            if f not in file_mod:
                continue
            data = (root / f).read_bytes()
            if len(data) > MAX_BYTES:
                skipped.append({"file": f, "reason": f"larger than {MAX_BYTES} bytes"})
                continue
            lang, adapter = LANGS[Path(f).suffix]
            try:   # a crash on one file never stops the scan
                r = adapter.parse(data, f, mod_by_id[file_mod[f]], reg, st)
                r["routes"] += _pattern_routes(st, lang, data, r, mod_by_id[file_mod[f]])
                r["mounts"] = stack.find_mounts(st, lang, decode(data), stack.import_names(r["imports"], lang))
                r["tables"] = _pattern_tables(st, lang, data, r, mod_by_id[file_mod[f]])
                r["queues"] = _pattern_queues(st, lang, data, r, mod_by_id[file_mod[f]])
                if lang in SPECS:
                    lines[f] = decode(data).count("\n") + 1
            except Exception as err:
                skipped.append({"file": f, "reason": f"parser failed: {type(err).__name__}: {err}"[:200]})
                continue
            results[f] = r
            if f.endswith(".scala"):   # kept only for `_declared`
                texts[f] = decode(data)
        protos = []
        for p in sorted(root.rglob("*.proto")):
            f = p.relative_to(root).as_posix()
            if (p.is_file() and not p.is_symlink() and not excluded(f, patterns) and not proto.vendored(f)
                    and p.stat().st_size <= MAX_BYTES):
                protos.append(proto.parse(p.read_text(encoding="utf-8", errors="replace"), f))

    _resolve_handlers(results, file_mod)
    for f, r in results.items():
        if f in lines:
            _file_node(r, f, file_mod[f], LANGS[Path(f).suffix][0], lines[f], reg)

    nodes: list[dict] = []
    packages: dict[str, dict] = {}
    for f, r in results.items():
        mid = file_mod[f]
        pid = ids.package_id(mid, r["package"])
        if pid not in packages:
            packages[pid] = {"id": pid, "kind": "package", "parent": mid, "name": r["package"],
                             "lang": mod_by_id[mid]["lang"], "file": Path(f).parent.as_posix(),
                             "line": 1, "visibility": "public", "metrics": {}}
        nodes.extend(r["nodes"])
    nodes = sorted(packages.values(), key=lambda n: n["id"]) + nodes

    _tapir(results, file_mod)

    _attach(nodes, results)
    _implements(nodes, results, file_mod)
    names = _module_names(modules, results, file_mod, build_names)
    internal = _internal(results, file_mod, mod_by_id, names, protos, aliases)
    typelinks.link(nodes, results, file_mod, lambda f, t: _relative_file(f, t, results), _family, internal)

    grpc_keys: dict[str, list[str]] = {}
    for p in protos:
        for svc in p["services"]:
            grpc_keys.setdefault(svc["name"], []).extend(r["key"] for r in svc["rpcs"])

    uses: dict[tuple[str, str], dict] = {}
    file_facts: dict[str, dict] = {}
    for f, r in results.items():
        lang = LANGS[Path(f).suffix][0]
        mid = file_mod[f]
        sinks, imports = [], []
        for imp in r["imports"]:
            imports.append({k: v for k, v in imp.items() if k not in ("names", "renames", "as")})
            for hit in stack.import_sinks(st, lang, imp):
                sinks.append({**hit, "line": imp["line"]})
            if imp["relative"]:
                hit = _relative_file(f, imp["target"], results)
                if hit is None:
                    continue
                other = file_mod[hit]
            else:
                other = _resolve_import(imp["target"], names.get(_scope(lang), {}), stack.sep(lang))
            if other and other != mid and (mid, other) not in uses:
                uses[(mid, other)] = {"id": ids.relation_id("uses-code", mid, other, None),
                                      "kind": "uses-code", "from": mid, "to": other, "key": None,
                                      "confidence": "confirmed",
                                      "evidence": [{"file": f, "line": imp["line"]}]}
        sql, urls = [], []
        for s in r["strings"]:
            if (q := facts.sql_facts(s["text"])) is not None:
                sql.append({**q, "line": s["line"], "in": s["in"]})
            for u in facts.url_facts(s["text"]):
                urls.append({"url": u, "text": facts.redact(s["text"])[:200], "line": s["line"], "in": s["in"]})
        file_facts[f] = {"imports": imports, "routes": r["routes"], "sql": sql, "urls": urls,
                         "sinks": sinks, "env_keys": r["env_keys"], "calls": r["calls"],
                         "includes": r.get("includes", []), "clients": r.get("clients", []),
                         "grpc": _grpc_ends(r, grpc_keys), "dags": r.get("dags", []),
                         "workflows": r.get("workflows", []), "reference_tasks": r.get("reference_tasks", [])}
        if r["mounts"]:   # likewise for mount entries
            file_facts[f]["mounts"] = r["mounts"]
        if r["tables"]:   # the key appears only where a table pattern matched
            file_facts[f]["tables"] = r["tables"]
        if r.get("queues"):   # likewise for in-process queue creation sites
            file_facts[f]["queues"] = r["queues"]

    file_node = {n["file"]: n["id"] for n in nodes if n["kind"] == "file"}
    first_node = {}
    for n in nodes:
        if n["kind"] in ("class", "method"):
            first_node.setdefault(n["file"], n["id"])
    return {
        "stack": stack.report(st, {f: {"lang": LANGS[Path(f).suffix][0], "imports": results[f]["imports"],
                                       "routes": file_facts[f]["routes"], "tables": file_facts[f].get("tables", []),
                                       "queues": file_facts[f].get("queues", []),
                                       "mounts": file_facts[f].get("mounts", []), "module": file_mod[f],
                                       "deduped": results[f].get("deduped", []),
                                       "src": texts.get(f, ""), "package": results[f]["package"]} for f in results},
                              internal,
                              {LANGS[Path(f).suffix][0] for f in results}),
        "meta": {"schema_version": SCHEMA_VERSION, "scanner_version": SCANNER_VERSION,
                 "repo": repo.name, "root": root_prefix, "commit": commit},
        "modules": modules,
        "nodes": nodes,
        "relations": sorted(uses.values(), key=lambda r: r["id"]),
        "files": {f: {"lang": LANGS[Path(f).suffix][0], "module": file_mod[f],
                      "node": file_node.get(f) or first_node.get(f) or ids.package_id(file_mod[f], results[f]["package"]),
                      "parse_error": results[f]["parse_error"]}
                  for f in results},
        "facts": file_facts,
        "proto": protos,
        "unassigned": unassigned,
        "skipped": skipped,
        "excluded": excluded_files,
        "stats": {"files": len(results), "modules": len(modules),
                  "classes": sum(1 for n in nodes if n["kind"] == "class"),
                  "methods": sum(1 for n in nodes if n["kind"] == "method"),
                  "parse_errors": sum(1 for r in results.values() if r["parse_error"]),
                  "seconds": round(time.time() - t0, 2)},
    }


def _service_keys(g: dict) -> str:
    """One gRPC service's keys, each written out in full (`grpc pkg.Svc/A, grpc pkg.Svc/B`) so the agent
    copies a key exactly as relations take it."""
    if not g["keys"]:
        return f"{g['service']} (no .proto in repo)"
    return ", ".join(g["keys"])


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _stack_lines(rep: dict) -> list[str]:
    """The Stack section: totals first, then what to sort into stack.yaml, then how each route pattern did."""
    if "unrecognised" not in rep:
        return []
    unrec, servers, pats = rep["unrecognised"], rep["servers_without_routes"], rep["patterns"]
    dead = [p for p in pats if stack.flagged(p)]
    if unrec or servers or dead:
        lines = [f"## Stack — {_plural(len(unrec), 'unrecognised import', 'unrecognised imports')}, "
                 f"{_plural(len(servers), 'server library', 'server libraries')} without routes, "
                 f"{_plural(len(dead), 'pattern', 'patterns')} with no match", ""]
    else:
        lines = ["## Stack — nothing unrecognised", ""]
    if unrec or servers:
        lines += ["Sort each into stack.yaml (imports, routes, effects or ignore); see SKILL.md § Stack.", ""]
    if unrec:
        lines.append(f"Unrecognised imports ({len(unrec)}):")
        lines += [f"- {u['lang']} `{u['prefix']}` — {_plural(u['files'], 'file', 'files')}: {', '.join(u['examples'])}"
                  for u in unrec]
        lines.append("")
    if servers:
        lines.append(f"Server libraries without routes ({len(servers)}):")
        lines += [f"- {x['lang']} `{x['prefix']}` ({x['kind']}) — {_plural(x['files'], 'file', 'files')} "
                  f"{'imports' if x['files'] == 1 else 'import'} it; no route pattern matched in them" for x in servers]
        lines.append("")
    for group, label, one0, many0 in (("routes", "Route patterns:", "route", "routes"),
                                    ("tables", "Table patterns:", "table", "tables"),
                                    ("queues", "Queue patterns:", "queue", "queues")):
        if mine := [p for p in pats if p["group"] == group]:
            lines.append(label)
            for p in mine:
                what = "annotation names" if p.get("form") == "annotated" else "regex"
                one, many = ("mount", "mounts") if p.get("mount") else (one0, many0)
                if p.get("duplicates"):
                    tail = f"duplicates {p['duplicates']}"
                elif stack.flagged(p):
                    tail = f"0 matches — check the {what} against {p['first_file']}"
                else:
                    tail = f"{_plural(p['matches'], one, many)} in {_plural(p['files'], 'file', 'files')}"
                lines.append(f"- {p['lang']} {p['name']} ({p['source']}): {tail}")
            lines.append("")
    if kinds := [o for o in rep.get("overrides", []) if "prefix" in o]:
        lines.append(f"Kinds changed by stack.yaml ({len(kinds)}):")
        lines += [f"- {o['lang']} `{o['prefix']}`: {o['pack_kind']} → {o['kind']}" for o in kinds]
        lines.append("")
    if entries := [o for o in rep.get("overrides", []) if "group" in o]:
        lines.append(f"Pack entries replaced by stack.yaml ({len(entries)}):")
        lines += [f"- {o['lang']} {o['group'][:-1]} {o['name']}: stack.yaml replaces the pack entry" for o in entries]
        lines.append("")
    return lines


def _table_line(t: tuple, names: dict[str, str]) -> str:
    table, f, line, where, kind = t
    name = names.get(where) or where
    return f"{table} ({f}:{line} {'defined on' if kind == 'defined' else 'in'} {name})"


def summary_md(s: dict) -> str:
    """Per-module digest the agent reads instead of the full structure.json."""
    root = s["meta"].get("root")
    where = f" — folder `{root}` of the repository" if root else ""
    lines = [readme.header("summary.md"), "",
             f"# Structure summary — {s['meta']['repo']} @ {s['meta']['commit'][:12]}{where}", "",
             f"Commit: {s['meta']['commit']}. Paths are relative to the scanned folder: read a file with "
             f"`git -C REPO show {s['meta']['commit'][:12]}:./<path>`.", "",
             f"Stats: {s['stats']}", ""]
    lines += _stack_lines(s.get("stack", {}))
    names = {n["id"]: n["name"] for n in s["nodes"]}
    for m in s["modules"]:
        files = [f for f, i in s["files"].items() if i["module"] == m["id"]]
        lines.append(f"## {m['id']} ({m['lang']}, {m['build']}, {len(files)} files)")
        routes_, clients, sinks, reads, writes, urls, envs = [], [], set(), set(), set(), set(), set()
        tables, queues = [], []
        grpc_ends: dict[tuple[str, str], list[str]] = {}
        dags, wfs, refs, mounts = [], [], [], []
        for f in files:
            ff = s["facts"][f]
            routes_ += [f"{r['method']} {r['path']} → {r['handler']} ({f}:{r['line']})" for r in ff["routes"]]
            mounts += [f"{x['path']}" + (f" → {x['target']}" if x["target"] else "") + f" ({f}:{x['line']})"
                       for x in ff.get("mounts", [])]
            tables += [(t["table"], f, t["line"], t["in"], t["kind"]) for t in ff.get("tables", [])]
            queues += [f"{q['delivery']} at {f}:{q['line']} in {names.get(q['in']) or q['in']}"
                       for q in ff.get("queues", [])]
            sinks |= {x["kind"] + ":" + x["lib"] for x in ff["sinks"]}
            for q in ff["sql"]:
                reads |= set(q["reads"])
                writes |= set(q["writes"])
            urls |= {u["url"] for u in ff["urls"]}
            envs |= {e["key"] for e in ff["env_keys"]}
            clients += [f"{c['method']} {c['path']} ← {c['in']} ({f}:{c['line']})" for c in ff.get("clients", [])]
            for g in ff.get("grpc", []):
                grpc_ends.setdefault((g["side"], _service_keys(g)), []).append(f"{g['in']} ({f}:{g['line']})")
            for d in ff.get("dags", []):
                sched = f"schedule `{d['schedule']}`" if d["schedule"] is not None else "no schedule set"
                dags.append(f"{d['id']} {sched} tasks [{', '.join(d['tasks'])}] → {d['node']} ({f}:{d['line']})")
            for w in ff.get("workflows", []):
                lps = "".join(f" launch plan {lp['name'] or '(default name)'} "
                              + (f"`{lp['schedule']}`" if lp["schedule"] is not None else "no schedule")
                              for lp in w["launch_plans"]) or " no launch plan in this file"
                wfs.append(f"{w['id']}{lps} → {w['node'] or 'defined elsewhere'} ({f}:{w['line']})")
            refs += [f"{t['kind']} project={t['project']} domain={t['domain']} name={t['name']} → {t['node']} "
                     f"({f}:{t['line']})" for t in ff.get("reference_tasks", [])]
            routes_ += [f"include_router({i['router']}, prefix={i['prefix']!r}) on {i['app']} ({f}:{i['line']})"
                        for i in ff.get("includes", [])]
        grpc_s = [f"{svc} ← {', '.join(at)}" for (side, svc), at in grpc_ends.items() if side == "server"]
        grpc_c = [f"{svc} ← {', '.join(at)}" for (side, svc), at in grpc_ends.items() if side == "client"]
        uses = [r["to"] for r in s["relations"] if r["from"] == m["id"]]
        for label, vals in (("uses-code", uses), ("routes", routes_), ("mounts", mounts), ("http clients", clients),
                            ("grpc servers", grpc_s), ("grpc clients", grpc_c), ("dags", dags),
                            ("flyte workflows", wfs), ("reference tasks", refs), ("sinks", sorted(sinks)),
                            ("sql reads", sorted(reads)), ("sql writes", sorted(writes)),
                            ("tables (patterns)", [_table_line(t, names) for t in sorted(tables)]),
                            ("in-process queues", queues),
                            ("url literals", sorted(urls)), ("env keys", sorted(envs))):
            if vals:
                lines.append(f"- **{label}:** " + "; ".join(vals))
        lines.append("")
    rpcs = [(r, p["file"]) for p in s.get("proto", []) for svc in p["services"] for r in svc["rpcs"]]
    if rpcs:
        lines.append("## Proto services (gRPC protocol keys)")
        lines += [f"- {r['key']}: {proto.describe(r)} ({f}:{r['line']})" for r, f in rpcs]
        lines.append("")
    if s["unassigned"]:
        lines.append(f"Unassigned files (no module): {', '.join(s['unassigned'])}")
    if s.get("excluded"):
        shown = ", ".join(s["excluded"][:30]) + (" …" if len(s["excluded"]) > 30 else "")
        lines.append(f"Excluded files ({len(s['excluded'])}): {shown}")
    if s["skipped"]:
        lines.append(f"Skipped files: {s['skipped']}")
    errs = [f for f, i in s["files"].items() if i["parse_error"]]
    if errs:
        lines.append(f"Files with parse errors (nodes may be partial): {', '.join(errs)}")
    return "\n".join(lines) + "\n"
