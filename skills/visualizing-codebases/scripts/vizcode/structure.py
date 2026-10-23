"""Structure pass: committed tree -> structure.json (nodes, uses-code relations, per-file facts)."""
from __future__ import annotations

import fnmatch
import posixpath
import re
import tempfile
import time
from pathlib import Path

from . import (SCANNER_VERSION, SCHEMA_VERSION, constructors, facts, generated, gitsrc, ids, proto, queue_use, readme,
               routes, sqlfiles, stack, typelinks, unscanned, wrappers)
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
# vendored code, matched against the whole path of a file in every language (generated files are scanned and
# reduced: generated.py)
VENDOR_EXCLUDES = [p for d in ("vendor", "third_party") for p in (f"*/{d}/*", f"{d}/*")] + ["node_modules/*"]
# build output, declaration files and Gradle build scripts, matched against the whole path of a file in a language of
# adapters/langs.py: Python and Scala build into `target`, `.venv` and `site-packages` (DEFAULT_EXCLUDES), and a
# Python package may be named `build` or `out`
BUILD_EXCLUDES = VENDOR_EXCLUDES + [p for d in ("dist", "build", "out", "bin", "obj", ".gradle", ".next", "coverage")
                                    for p in (f"*/{d}/*", f"{d}/*")] + ["*.min.js", "*.d.ts", "*.gradle.kts"]
# Cargo's extra binaries (`src/bin/*.rs`) are source, not build output
BIN_EXCLUDES = ("*/bin/*", "bin/*")
# matched against the file name only; a table's test glob with a folder in it is matched against the path
TEST_FILES = ["test_*.py", "*_test.py", "conftest.py", "*Spec.scala", "*Test.scala", "*Suite.scala",
              *dict.fromkeys(t for spec in BY_SUFFIX.values() for t in spec.tests if "/" not in t)]
# EF Core's generated migration files: each holds a full copy of the model (`ToTable` of every table)
EF_MIGRATIONS = [p for g in ("Migrations/*.Designer.cs", "Migrations/*ModelSnapshot.cs") for p in (g, "*/" + g)]
GENERIC_EXCLUDES = {suf: BUILD_EXCLUDES + [p for t in spec.tests if "/" in t for p in (t, "*/" + t)]
                    + (EF_MIGRATIONS if suf == ".cs" else []) for suf, spec in BY_SUFFIX.items()}
GENERIC_EXCLUDES |= {".py": VENDOR_EXCLUDES, ".scala": VENDOR_EXCLUDES}
LONE_CR = re.compile(rb"\r(?!\n)")
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
        for cid, supers in r.get("supers", []) + r.get("bases", []):
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


def _go_implements(nodes: list[dict]) -> None:
    """Go interfaces are structural: a Go type whose methods include every method of a repo interface (same name
    and arity) implements it. An interface is a type whose methods are all declared inside it (a struct's attach
    from elsewhere)."""
    methods: dict[str, list[dict]] = {}
    classes = {}
    for n in nodes:
        if n["lang"] != "go":
            continue
        if n["kind"] == "class":
            classes[n["id"]] = n
        elif n["kind"] == "method" and n.get("parent"):
            methods.setdefault(n["parent"], []).append(n)

    def inside(m: dict, c: dict) -> bool:
        return m["file"] == c["file"] and c["line"] <= m["line"] < c["line"] + c["metrics"]["loc"]

    sigs = {cid: {(m["name"], m["id"].rsplit("/", 1)[-1]) for m in ms} for cid, ms in methods.items()}
    ifaces = [cid for cid, ms in methods.items() if cid in classes and all(inside(m, classes[cid]) for m in ms)]
    for cid in sorted(methods):
        if cid not in classes or cid in ifaces:
            continue
        hits = [i for i in ifaces if sigs[i] <= sigs[cid]]
        if hits:
            classes[cid]["implements"] = sorted(set(classes[cid].get("implements", [])) | set(hits))


def _grpc_text(text: str, r: dict, lang: str) -> list[dict]:
    """The gRPC ends of proto.text_ends in one file's source, each with its line and the method (else class) it
    sits in; JavaScript and TypeScript `new <pkg>.<S>(` only in a file that imports a gRPC library."""
    js = lang in ("javascript", "typescript") and any("grpc" in i["target"] for i in r["imports"])
    spans = _spans(r, "method") + _spans(r, "class")
    out = []
    for side, name, pos in proto.text_ends(text, js):
        line = text.count("\n", 0, pos) + 1
        inside = [s for s in spans if s[0] <= line <= s[1]]
        if inside:
            out.append({"side": side, "name": name, "line": line, "in": min(inside, key=lambda s: s[1] - s[0])[2]})
    return out


def _bases(r: dict) -> list[tuple[str, list[str]]]:
    return list(r.get("bases", [])) + list(r.get("supers", []))


def _grpc_impls(results: dict[str, dict], keys: dict[str, list[str]]) -> dict[str, str]:
    """Class name -> the gRPC service it implements, from its bases, for registrations that name the class."""
    out: dict[str, str] = {}
    for r in results.values():
        by_id = {n["id"]: n for n in r["nodes"]}
        for cid, bases in _bases(r):
            for b in bases:
                if (svc := proto.base_end(b)) and (svc in keys or proto.generated(b)):
                    out.setdefault(by_id[cid]["name"], svc)
    return out


def _grpc_ends(r: dict, keys: dict[str, list[str]], impls: dict[str, str]) -> list[dict]:
    """gRPC client stubs and server implementations in one file, with the proto keys of their service."""
    by_id = {n["id"]: n for n in r["nodes"]}
    out = []

    def end(side: str, svc: str, where: str, line: int) -> None:
        out.append({"side": side, "service": svc, "keys": keys.get(svc, []), "in": where, "line": line})

    for cid, bases in _bases(r):
        for b in bases:
            if (svc := proto.base_end(b)) and (svc in keys or proto.generated(b)):
                end("server", svc, cid, by_id[cid]["line"])
    for n in r["nodes"]:
        for fld in n.get("fields") or []:
            if svc := proto.field_end(fld):
                end("server", svc, n["id"], n["line"])
    for c in r["calls"]:
        if c.get("in") and (e := proto.call_end(c["callee"])) and (e[1] in keys or proto.generated(c["callee"])):
            end(*e, c["in"], c["line"])
    for t in r.get("grpc_text", []):
        svc = impls.get(t["name"]) if t["side"] == "server-impl" else t["name"]
        if svc in keys:
            end("client" if t["side"] == "client" else "server", svc, t["in"], t["line"])
    return sorted(out, key=lambda e: e["line"])


def _proto_messages(protos: list[dict], modules: list[dict], nodes: list[dict], packages: dict[str, dict],
                    reg: ids.IdRegistry) -> list[dict]:
    """Class nodes (lang `proto`, with fields) for the messages of each .proto inside a module, in the package the
    .proto declares; a message (and the messages nested in it) is skipped where the module already has a class of its
    name (generated code)."""
    out: list[dict] = []
    for p in protos:
        owners = [m for m in modules if m["path"] == "." or p["file"].startswith(m["path"] + "/")]
        if not owners:
            continue
        mod = max(owners, key=lambda m: 0 if m["path"] == "." else len(m["path"]))
        pkg = p["package"] or "_root_"
        pid = ids.package_id(mod["id"], pkg)
        prefix = ids.mod_path(mod["id"]) + "::"
        taken = {n["name"] for n in nodes + out if n["kind"] == "class" and n["id"].startswith(prefix)}
        made: dict[str, str] = {}
        skipped: set[str] = set()
        for msg in p["messages"]:
            outer, _, name = msg["name"].rpartition(".")
            if name in taken or outer in skipped:
                skipped.add(msg["name"])
                continue
            nid = reg.claim(ids.qualified(mod["id"], f"{pkg}.{msg['name']}"))
            made[msg["name"]] = nid
            out.append({"id": nid, "kind": "class", "parent": made.get(outer, pid), "name": name, "lang": "proto",
                        "file": p["file"], "line": msg["line"], "visibility": "public",
                        "metrics": {"loc": msg["loc"], "methods": 0}, **({"fields": msg["fields"]} if msg["fields"] else {})})
        if made:
            packages.setdefault(pid, {"id": pid, "kind": "package", "parent": mod["id"], "name": pkg,
                                      "lang": mod["lang"], "file": Path(p["file"]).parent.as_posix(),
                                      "line": 1, "visibility": "public", "metrics": {}})
    return out


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
    """Create the file node of a generic-walker file whose route handler, table or queue site is the file itself (an
    inline function, a file of no functions), as the walker creates it on a top-level function. Runs after
    _resolve_handlers: a route whose handler name resolves needs none."""
    facts = [x for x in (*r["routes"], *r["tables"], *r.get("queues", []))
             if NEW_FILE_NODE in (x.get("handler"), x.get("in"))]
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


def _pattern_routes(st: stack.Stack, lang: str, data: bytes, r: dict, module: dict, imports: list[str]) -> list[dict]:
    """Route facts from the route patterns of the packs and stack.yaml (imports: what `when` is matched against). A
    regex route's handler is the method around the match; failing that, the file (_file_id). An annotated route's
    handler is the annotated method (the generic walker's recorded annotations). The file's mounts (r["mounts"])
    compose onto the regex routes registered on them (stack.compose)."""
    src = decode(data)
    found = stack.find_routes(st, lang, src, imports, _spans(r, "method"), _file_id(r, module, lang),
                              r.get("mounts")) \
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


ALIASED_HEAD = re.compile(r"(\$?)([A-Za-z_]\w*)")


def _in_repo(f: str, imp: dict, results: dict[str, dict], names: dict[str, dict[str, str]]) -> str | None:
    """The module an import of file f names, when it is the repo's own (a relative file, or a module name)."""
    if imp["relative"]:
        hit = _relative_file(f, imp["target"], results)
        return None if hit is None else hit
    return _resolve_import(imp["target"], names.get(_scope(_lang(f)), {}), stack.sep(_lang(f)))


def _unalias(f: str, r: dict, results: dict[str, dict], names: dict[str, dict[str, str]]) -> None:
    """Write a repo name the file imports under another name (`import a.Article as ArticleIO`, `use X as Y`) as
    the name it imports: at the head of each call, in each class's bases and each route's named handler, so they
    resolve like the plain name. A handler class takes its import's namespace, which tells it from a same-named
    class imported plainly. A library's name renamed away from a local one (`join as joinPath`) is left alone."""
    renamed = {local: (member, imp["target"]) for imp in r["imports"] if _in_repo(f, imp, results, names)
               for local, member in (imp.get("renames") or {}).items()}
    if not renamed:
        return

    def plain(text: str, qualify: bool = False) -> str:
        m = ALIASED_HEAD.match(text)
        if not m or m.group(2) not in renamed:
            return text
        member, target = renamed[m.group(2)]
        if qualify and not text[m.end():]:
            segs = _segments(target)
            return "/".join(segs + ([member] if segs[-1:] != [member] else []))
        return m.group(1) + member + text[m.end():]
    for c in r["calls"]:
        c["callee"] = plain(c["callee"])
    for route in r["routes"]:
        for key in ("handler_name", "handler_class"):
            if route.get(key):
                route[key] = plain(route[key], key == "handler_class")
    for key in ("supers", "bases"):
        if key in r:
            r[key] = [(cid, [plain(x) for x in supers]) for cid, supers in r[key]]


def _import_hints(r: dict, f: str, name: str, qualifier: str | None, results: dict[str, dict]) -> list[str | tuple]:
    """Where the file's imports say a handler name comes from: a file (a relative import naming it), or the last
    package segment of an import that names it or its qualifier (`use crate::routes::h`, `from app.views import h`,
    `import h "x/handlers"` for `h.Get`)."""
    out: list[str | tuple] = []
    for imp in r["imports"]:
        parts = [x for x in re.split(r"::|[./\\]", imp["target"]) if x and x not in ("crate", "self", "super")]
        if name in imp.get("names") or []:
            hit = _relative_file(f, imp["target"], results) if imp["relative"] else None
            out.append(hit or tuple(parts[-1:]))
        elif parts and parts[-1] == name and len(parts) > 1:
            out.append(tuple(parts[-2:-1]))
        elif qualifier and parts and qualifier in (imp.get("as"), parts[-1]):
            out.append(tuple(parts[-1:]))
    return out


def _qualified(r: dict, cls: str) -> str:
    """A bare class name the file imports, written with the namespace it is imported from (`ScrobbleController`
    -> `App/Http/Controllers/API/ScrobbleController`), so two same-named classes are told apart."""
    if len(_segments(cls)) > 1:
        return cls
    for imp in r["imports"]:
        if cls in (imp.get("names") or []) and not imp["relative"]:
            return "/".join(_segments(imp["target"]) + [cls])
    return cls


def _route_lambda(r: dict, route: dict) -> dict | None:
    """The inline function a route registers inside its enclosing method (`r.Get("/x", func(..) {..})`, Ktor
    `get("/x") { .. }`): the outermost lambda of that method starting on the route's line, as a
    nested record named after the route (`get_ping`); None when there is none."""
    here = [x for x in r.get("lambdas", []) if x["in"] == route["handler"]
            and x["start"] == route["line"] and not x.get("node")]
    if not here:
        return None
    lam = min(here, key=lambda x: (x["start"], -x["end"]))
    words = [w for w in re.split(r"[^A-Za-z0-9]+", route["path"]) if w]
    lam.update(name="_".join([route["method"].lower(), *words]) or route["method"].lower(), line=lam["start"],
               params=[])
    r.setdefault("nested", []).append(lam)
    return lam


def _nested_node(r: dict, nested: dict, reg: ids.IdRegistry) -> str:
    """Make a nested function a method node of its enclosing function's owner, `<owner>#<outer>.<name>/<arity>`,
    and move the calls, strings, tables and queues inside it from the enclosing function to it."""
    by_id = {n["id"]: n for n in r["nodes"]}
    outer = by_id[nested["in"]]
    label = outer["id"].split("#", 1)[1].rsplit("/", 1)[0] + "." + nested["name"]
    nid = reg.claim(ids.method_id(outer["parent"], label, len(nested["params"])))
    r["nodes"].append({"id": nid, "kind": "method", "parent": outer["parent"], "name": nested["name"],
                       "lang": outer["lang"], "file": outer["file"], "line": nested["start"], "visibility": "private",
                       "metrics": {"loc": nested["end"] - nested["start"] + 1},
                       "signature": {"params": nested["params"], "returns": None}})
    if (owner := by_id.get(outer["parent"])) is not None:
        owner["metrics"]["methods"] = owner["metrics"].get("methods", 0) + 1
    for group in ("calls", "strings", "tables", "queues"):
        for x in r.get(group, []):
            if x.get("in") == outer["id"] and nested["start"] <= x["line"] <= nested["end"]:
                x["in"] = nid
    for other in r["nested"]:
        if other is not nested and other["in"] == outer["id"] and nested["start"] <= other["line"] <= nested["end"]:
            other["in"] = nid
    nested["node"] = nid
    return nid


def _resolve_handlers(results: dict[str, dict], file_mod: dict[str, str], reg: ids.IdRegistry,
                      names: dict[str, dict[str, str]]) -> None:
    """Replace the span-rule handler of a route that names one (`handler_name`) with the method or function of
    that name (its last `.` or `::` segment: `h.GetOrder`, `handlers::get_order`): among those the file's imports
    point at (_import_hints) when any, and for a bare name the free functions when any, the one in the same file,
    else the same package, else the module. Ambiguity at a level, or no match, leaves a function of that name
    nested in the span-rule handler (made a node: _nested_node), else the file: never the function that registers
    the route. A route that names no handler but sits on a nested function's decorators is that function's.
    A route whose pattern names its handler by convention (`handler_class`, `handler_method`) is that method when
    its module has exactly one class of that name (the last `::`, `.` or `/` segment of both names; the segments
    before it, when cls has any, must end the package and outer classes in the class id) holding a method of that
    name; else the rules above."""
    methods: dict[tuple[str, str], list[tuple[str, str, str]]] = {}   # (module, name) -> (file, package, id)
    owner_kind: dict[str, str] = {}
    for f, r in results.items():
        for n in r["nodes"]:
            owner_kind[n["id"]] = n["kind"]
            if n["kind"] == "method":
                methods.setdefault((file_mod[f], n["name"]), []).append((f, r["package"], n["id"]))
    anywhere: dict[str, list[tuple[str, str, str]]] = {}   # name -> methods of that name in every module
    for (_, name), found in methods.items():
        anywhere.setdefault(name, []).extend(found)
    parent = {n["id"]: n.get("parent") for r in results.values() for n in r["nodes"]}
    classes: dict[tuple[str, str], list[str]] = {}       # (module, class name) -> class ids
    any_classes: dict[str, list[str]] = {}               # class name -> class ids in every module
    members: dict[tuple[str, str], list[str]] = {}       # (class id, method name) -> method ids
    for f, r in results.items():
        for n in r["nodes"]:
            if n["kind"] == "class":
                # by the name's last segment: Ruby `class Admin::OrdersController` is named `Admin.OrdersController`
                classes.setdefault((file_mod[f], _segments(n["name"])[-1]), []).append(n["id"])
                any_classes.setdefault(_segments(n["name"])[-1], []).append(n["id"])
            elif n["kind"] == "method" and owner_kind.get(n.get("parent") or "") == "class":
                members.setdefault((n["parent"], n["name"]), []).append(n["id"])
    for f, r in results.items():
        for route in r["routes"]:
            cls, meth = route.pop("handler_class", None), route.pop("handler_method", None)
            if cls:
                cls = _qualified(r, cls)
                # a class the file names with its namespace may sit in another module
                mine = classes.get((file_mod[f], _segments(cls)[-1]), [])
                pool = mine if len(_segments(cls)) == 1 else (mine + [c for c in any_classes.get(_segments(cls)[-1], [])
                                                                     if c not in mine])
            if cls and (found := _conventional_handler(cls, meth, pool, members)):
                route.pop("handler_name", None)
                route.pop("nested_handler", None)
                route["handler"] = found
                continue
            name = route.pop("handler_name", None) or route.pop("nested_handler", None)
            nested = [x for x in r.get("nested", []) if x["in"] == route["handler"]]
            if not name:
                below = [x for x in nested if x["start"] <= route["line"] <= x["line"]]
                if len(below) == 1:
                    route["handler"] = below[0].get("node") or _nested_node(r, below[0], reg)
                elif lam := _route_lambda(r, route):
                    route["handler"] = _nested_node(r, lam, reg)
                continue
            parts = re.split(r"\.|::", name)
            cands = methods.get((file_mod[f], parts[-1]), [])
            hints = _import_hints(r, f, parts[-1], parts[-2] if len(parts) > 1 else None, results)

            def hinted(found: list) -> list:
                return [c for c in found if any(h == c[0] if isinstance(h, str)
                                                else set(h) <= {*Path(c[0]).parent.parts, Path(c[0]).stem}
                                                for h in hints)]
            # the module's own, as the imports point; else another repo module's an import naming it points at
            into = {m for imp in r["imports"] if (parts[-1] in (imp.get("names") or [])
                                                   or _segments(imp["target"])[-1:] in ([parts[-1]], parts[-2:-1]))
                    and (m := _in_repo(f, imp, results, names)) is not None}
            into = {file_mod.get(m, m) for m in into}   # a relative import names a file: its module
            far = [c for c in anywhere.get(parts[-1], []) if c not in cands and file_mod[c[0]] in into]
            cands = hinted(cands) or hinted(far) or cands
            if len(parts) == 1:
                cands = [c for c in cands if owner_kind.get(parent.get(c[2]) or "") == "file"] or cands
            found = None
            for level in (lambda c: c[0] == f, lambda c: c[1] == r["package"], lambda c: True):
                hit = [c for c in cands if level(c)]
                if len(hit) == 1:
                    found = hit[0][2]
                if hit:
                    break
            if found is None and len(mine := [x for x in nested if x["name"] == parts[-1]]) == 1:
                found = mine[0].get("node") or _nested_node(r, mine[0], reg)
            if found is None and owner_kind.get(route["handler"]) == "method":
                found = next((n["id"] for n in r["nodes"] if n["kind"] == "file"),
                             NEW_FILE_NODE if Path(f).suffix in BY_SUFFIX else None)
            if found is not None:
                route["handler"] = found


def _base_paths(st: stack.Stack, results: dict[str, dict]) -> None:
    """Prefix each route with the stack.yaml base path of the longest folder holding its file."""
    for f, r in results.items():
        under = [d for d in st.base_paths if d == "." or f.startswith(d + "/")]
        if under and r["routes"]:
            prefix = st.base_paths[max(under, key=lambda d: (d != ".", len(d)))]
            for route in r["routes"]:
                route["path"] = stack.normalise(prefix.rstrip("/") + "/" + route["path"].lstrip("/"))


def _bodyless_spans(r: dict) -> list[tuple[int, int]]:
    """The lines of each class whose every method is bodyless (an interface: a declarative client's mappings
    describe calls out, not routes)."""
    bodyless = set(r.get("bodyless", []))
    methods: dict[str, list[str]] = {}
    for n in r["nodes"]:
        if n["kind"] == "method":
            methods.setdefault(n.get("parent") or "", []).append(n["id"])
    return [(n["line"], n["line"] + n.get("metrics", {}).get("loc", 1) - 1) for n in r["nodes"]
            if n["kind"] == "class" and methods.get(n["id"]) and set(methods[n["id"]]) <= bodyless]


IMPLEMENTED_KINDS = ("sql-db", "doc-db", "http-out", "http")
SUMMARY_CHUNK = 25   # items per summary.md module line


def _implemented(r: dict, sinks: list[dict]) -> list[dict]:
    """Interfaces a framework implements: in a file importing a database or HTTP client library, a class whose
    every method is bodyless (a repository, a declarative HTTP client), with its bases and first annotation."""
    if not any(x["kind"] in IMPLEMENTED_KINDS for x in sinks) or not r.get("bodyless"):
        return []
    bodyless = set(r["bodyless"])
    methods: dict[str, list[dict]] = {}
    for n in r["nodes"]:
        if n["kind"] == "method":
            methods.setdefault(n.get("parent") or "", []).append(n)
    bases = dict(r.get("supers", []))
    notes = {}
    for a in r.get("annotations", []):
        notes.setdefault(a["node"], a["text"])
    return [{"class": n["name"], "line": n["line"], "methods": [m["name"] for m in methods[n["id"]]],
             "bases": bases.get(n["id"], []), "annotation": notes.get(n["id"])}
            for n in r["nodes"] if n["kind"] == "class" and methods.get(n["id"])
            and all(m["id"] in bodyless for m in methods[n["id"]])]


def _client_heads(st: stack.Stack, r: dict, lang: str) -> list[str]:
    """The local names a file gives the HTTP client libraries it imports (`axios`, `HttpClient`, `requests`)."""
    out = []
    for imp in r["imports"]:
        if any(h["kind"] in ("http-out", "http") for h in stack.import_sinks(st, lang, imp)):
            out += [*(imp.get("names") or []), *(imp.get("renames") or {}), imp.get("as") or "",
                    re.split(r"[./\\:]+", imp["target"])[-1]]
    return [x for x in out if x]


def _segments(name: str) -> list[str]:
    return [x for x in re.split(r"::|[./\\]", name) if x]


def _conventional_handler(cls: str, meth: str, cands: list[str], members: dict) -> str | None:
    """The method `meth` of the one class among cands that `cls` names (see _resolve_handlers), else None."""
    outer = [x.lower() for x in _segments(cls)[:-1]]
    if outer:   # a named namespace: the class id's package and outer-class segments end with cls's own
        cands = [c for c in cands if [x.lower() for x in _segments(c.split("::", 1)[-1])[:-1]][-len(outer):] == outer]
    if len(cands) != 1:
        return None
    hits = members.get((cands[0], meth), [])
    return hits[0] if len(hits) == 1 else None


GLOBAL_USING = re.compile(r"^\s*global\s+using\s+(?:static\s+)?(?:\w+\s*=\s*)?([\w.]+)\s*;", re.M)
CSPROJ_USING = re.compile(r"<Using\s+Include\s*=\s*\"([\w.]+)\"")


def _project_usings(root: Path, files: list[str], file_mod: dict[str, str], modules: list[dict]) -> dict[str, list[str]]:
    """C# namespaces every file of a project imports (module id -> names): its files' `global using` lines and its
    .csproj `<Using Include>` items. A pack's `when` matches them in every file of the project."""
    out: dict[str, set[str]] = {}
    for f in files:
        if f.endswith(".cs") and f in file_mod and (root / f).stat().st_size <= MAX_BYTES:
            out.setdefault(file_mod[f], set()).update(GLOBAL_USING.findall(decode((root / f).read_bytes())))
    for m in modules:
        if m["lang"] == "csharp":
            for proj in sorted((root / m["path"]).glob("*.csproj")):
                out.setdefault(m["id"], set()).update(CSPROJ_USING.findall(proj.read_text(encoding="utf-8",
                                                                                         errors="replace")))
    return {mid: sorted(names) for mid, names in out.items() if names}


def _pattern_tables(st: stack.Stack, lang: str, data: bytes, r: dict, module: dict, imports: list[str]) -> list[dict]:
    """Table facts from the table patterns of the packs and stack.yaml. Two patterns giving the same (table,
    line, in) give one fact, named after the pattern listed first; one pattern's own matches stay. In a
    generic-walker language a class defines one table: when patterns name different tables defined on one class
    (JPA `@Entity(name = ...)` and `@Table(name = ...)`), the pattern listed first keeps its facts."""
    found = stack.find_tables(st, lang, decode(data), imports,
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


def _pattern_queues(st: stack.Stack, lang: str, data: bytes, r: dict, module: dict, imports: list[str]) -> list[dict]:
    """In-process queue creation sites from the queue patterns of the packs and stack.yaml, one per (line, in)."""
    src, spans = decode(data), _spans(r, "method")
    found = stack.find_queues(st, lang, src, imports, spans, _file_id(r, module, lang))
    kept = _dedupe(st.queues, lang, found, "queues", "pattern", ("line", "in"), r)
    regex = {p.name: p.regex for p in st.queues if p.lang == lang}
    for q in kept:
        if q["source"] == "pack":
            q["use"] = queue_use.site_use(src, q["line"], regex[q["pattern"]], spans, q["in"])
    return kept



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
                for method, path in routes.tapir_uses(body, known, r["tapir"].get("consts")):
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
    patterns = DEFAULT_EXCLUDES + st.excludes + (extra_excludes or []) \
        + ([out_dir.rstrip("/") + "/*"] if out_dir else [])
    results: dict[str, dict] = {}
    texts: dict[str, str] = {}
    sources: dict[str, str] = {}   # every scanned file's text, for the HTTP client wrappers (dropped after)
    lines: dict[str, int] = {}     # a generic-walker file's line count, for a file node made after the scan
    skipped: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in gitsrc.export_tree(repo, commit, root):
            skipped.append({"file": name, "reason": "link points outside the repository; not extracted"})
        if (root / "build.sbt").exists():
            patterns.append(SBT_BUILD_DIR)
        tree = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.is_symlink())
        files = [f for f in tree if Path(f).suffix in LANGS]
        excluded_files = [f for f in files if excluded(f, patterns) or generated.bundle(f, root / f)]
        dropped = set(excluded_files)
        files = [f for f in files if f not in dropped]
        modules, file_mod, unassigned = detect_modules(root, files)
        mod_by_id = {m["id"]: m for m in modules}
        build_names, aliases = names_from_build_files(root, modules), path_aliases(root, modules)
        reg = ids.IdRegistry()
        usings = _project_usings(root, files, file_mod, modules)
        gen_files: list[str] = []
        for f in files:
            if f not in file_mod:
                continue
            data = LONE_CR.sub(b"\n", (root / f).read_bytes())   # old Mac line ends: same length, so offsets hold
            if f.endswith(generic.SFC_SUFFIXES):
                data = generic.script_blocks(data)   # a single-file component: its script blocks alone
            if len(data) > MAX_BYTES:
                skipped.append({"file": f, "reason": f"larger than {MAX_BYTES} bytes"})
                continue
            lang, adapter = LANGS[Path(f).suffix]
            try:   # a crash on one file never stops the scan
                r = adapter.parse(data, f, mod_by_id[file_mod[f]], reg, st)
                names = stack.import_names(r["imports"], lang) + usings.get(file_mod[f], [])
                r["mounts"] = stack.find_mounts(st, lang, decode(data), names)
                r["routes"] += _pattern_routes(st, lang, data, r, mod_by_id[file_mod[f]], names)
                sources[f] = decode(data)
                if any(h["kind"] in stack.SERVER_KINDS for imp in r["imports"] for h in stack.import_sinks(st, lang, imp)):
                    r["route_like"] = [x for x in stack.route_like(decode(data), lang)
                                       if not any(a <= x["line"] <= b for a, b in _bodyless_spans(r))]
                r["tables"] = _pattern_tables(st, lang, data, r, mod_by_id[file_mod[f]], names)
                r["untabled"] = stack.entities_without_table(r, any(
                    h["kind"] in stack.DB_KINDS for imp in r["imports"] for h in stack.import_sinks(st, lang, imp)))
                r["queues"] = _pattern_queues(st, lang, data, r, mod_by_id[file_mod[f]], names)
                r["grpc_text"] = _grpc_text(decode(data), r, lang)
                if lang in SPECS:
                    lines[f] = decode(data).count("\n") + 1
            except Exception as err:
                skipped.append({"file": f, "reason": f"parser failed: {type(err).__name__}: {err}"[:200]})
                continue
            results[f] = r
            if generated.generated(f, decode(data)):
                gen_files.append(f)
            if f.endswith(".scala"):   # kept only for `_declared`
                texts[f] = decode(data)
        protos = []
        for p in sorted(root.rglob("*.proto")):
            f = p.relative_to(root).as_posix()
            if (p.is_file() and not p.is_symlink() and not excluded(f, patterns) and not proto.vendored(f)
                    and p.stat().st_size <= MAX_BYTES):
                protos.append(proto.parse(p.read_text(encoding="utf-8", errors="replace"), f))
        not_scanned = unscanned.report(tree, set(results), lambda f: excluded(f, patterns + BUILD_EXCLUDES),
                                       lambda f: (root / f).read_text(encoding="utf-8", errors="replace"))
        mapper_sql, sql_files = sqlfiles.read(root, tree, lambda f: excluded(f, patterns + BUILD_EXCLUDES)
                                              or (root / f).stat().st_size > MAX_BYTES)

    names = _module_names(modules, results, file_mod, build_names)
    for f, r in results.items():
        _unalias(f, r, results, names)
    _resolve_handlers(results, file_mod, reg, names)
    for f, r in results.items():
        if f in lines:
            _file_node(r, f, file_mod[f], LANGS[Path(f).suffix][0], lines[f], reg)
    wrappers.find(results, sources, lambda f: _client_heads(st, results[f], LANGS[Path(f).suffix][0]))
    sources.clear()
    handlers = {route["handler"] for r in results.values() for route in r["routes"]}
    for f in gen_files:
        generated.keep_needed(results[f], handlers, LANGS[Path(f).suffix][0])
        results[f]["grpc_text"] = []

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
    nodes += _proto_messages(protos, modules, nodes, packages, reg)
    nodes = sorted(packages.values(), key=lambda n: n["id"]) + nodes

    _tapir(results, file_mod)
    _base_paths(st, results)

    _attach(nodes, results)
    _implements(nodes, results, file_mod)
    _go_implements(nodes)
    names = _module_names(modules, results, file_mod, build_names)
    internal = _internal(results, file_mod, mod_by_id, names, protos, aliases)
    constructors.mark(nodes, {cid for r in results.values() for cid in r.get("values", [])},
                      {fid for r in results.values() for fid in r.get("class_inits", [])})
    typelinks.link(nodes, results, file_mod, lambda f, t: _relative_file(f, t, results), _family, internal)

    grpc_keys: dict[str, list[str]] = {}
    for p in protos:
        for svc in p["services"]:
            have = grpc_keys.setdefault(svc["name"], [])
            have += [r["key"] for r in svc["rpcs"] if r["key"] not in have]
    impls = _grpc_impls(results, grpc_keys)

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
        written_out = facts.text_output_scopes(r["calls"])
        for s in r["strings"]:
            if s["in"] not in written_out and (q := facts.sql_facts(s["text"])) is not None:
                sql.append({**q, "line": s["line"], "in": s["in"]})
            for u in facts.url_facts(s["text"]):
                urls.append({"url": u, "text": facts.redact(s["text"])[:200], "line": s["line"], "in": s["in"]})
        file_facts[f] = {"imports": imports, "routes": r["routes"], "sql": sql, "urls": urls,
                         "sinks": sinks, "env_keys": r["env_keys"], "calls": r["calls"],
                         "includes": r.get("includes", []), "clients": r.get("clients", []),
                         "grpc": _grpc_ends(r, grpc_keys, impls), "dags": r.get("dags", []),
                         "workflows": r.get("workflows", []), "reference_tasks": r.get("reference_tasks", [])}
        if r["mounts"]:   # likewise for mount entries
            file_facts[f]["mounts"] = r["mounts"]
        if implemented := _implemented(r, sinks):
            file_facts[f]["implemented"] = implemented
        if r["tables"]:   # the key appears only where a table pattern matched
            file_facts[f]["tables"] = r["tables"]
        if queues := queue_use.handled(r.get("queues", []), r["imports"], internal.get(lang, set()), lang):
            file_facts[f]["queues"] = queues   # likewise for in-process queue creation sites

    sqlfiles.attach(mapper_sql, nodes, file_facts)
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
                                       "route_like": results[f].get("route_like", []),
                                       "untabled": results[f].get("untabled", []),
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
        "generated": gen_files,
        "unscanned": not_scanned,
        "sql_files": sql_files,
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
    missed, untabled = rep.get("routes_unmatched", []), rep.get("entities_without_table", [])
    dead = [p for p in pats if stack.flagged(p)]
    if unrec or servers or dead or missed:
        lines = [f"## Stack — {_plural(len(unrec), 'unrecognised import', 'unrecognised imports')}, "
                 f"{_plural(len(servers), 'server library', 'server libraries')} without routes, "
                 f"{_plural(len(dead), 'pattern', 'patterns')} with no match"
                 + (f", {_plural(sum(len(x['lines']) for x in missed), 'route-looking line', 'route-looking lines')}"
                    " with no route" if missed else ""), ""]
    else:
        lines = ["## Stack — nothing unrecognised", ""]
    if unrec or servers:
        lines += ["Sort each into stack.yaml (imports, routes, effects or ignore); see SKILL.md § Stack.", ""]
    if unrec:
        lines.append(f"Unrecognised imports ({len(unrec)}):")
        lines += [f"- {u['lang']} `{u['prefix']}` — {_plural(u['files'], 'file', 'files')}: {', '.join(u['examples'])}"
                  + (f" (looks like a {u['looks_like']} library)" if u.get("looks_like") else "") for u in unrec]
        lines.append("")
    if servers:
        lines.append(f"Server libraries without routes ({len(servers)}):")
        lines += [f"- {x['lang']} `{x['prefix']}` ({x['kind']}) — {_plural(x['files'], 'file', 'files')} "
                  f"{'imports' if x['files'] == 1 else 'import'} it; no route pattern matched in them" for x in servers]
        lines.append("")
    if missed:
        n = sum(len(x["lines"]) for x in missed)
        lines.append(f"Route-looking lines with no route ({n} in {_plural(len(missed), 'file', 'files')}): a route "
                     "style no pattern reads; add a stack.yaml route pattern, or say in problems why they are none:")
        lines += [f"- {x['lang']} {x['file']}: {'line' if len(x['lines']) == 1 else 'lines'} "
                  f"{', '.join(map(str, x['lines']))} — `{x['example']}`" for x in missed]
        lines.append("")
    if untabled:
        n = sum(len(x["classes"]) for x in untabled)
        lines.append(f"Entity-looking classes with no table ({n} in {_plural(len(untabled), 'file', 'files')}; not "
                     "counted above): the table name comes from a naming default (the class name, its snake-case "
                     "plural) or a style no pattern reads; write their tables into meaning.json by the ORM's rule, "
                     "or add a table pattern:")
        lines += [f"- {x['lang']} {x['file']}: " + ", ".join(f"{c} (line {ln})" for c, ln in zip(x["classes"], x["lines"]))
                  for x in untabled]
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


def _unscanned_lines(rep: dict) -> list[str]:
    """The Not scanned section: source in languages without a reader, and the deployables made mostly of it."""
    langs, deps = rep.get("languages", []), rep.get("deployables", [])
    if not langs and not deps:
        return []
    lines = [f"## Not scanned — {_plural(len(langs), 'language', 'languages')} without a reader, "
             f"{_plural(len(deps), 'deployable', 'deployables')} mostly in them", ""]
    if langs:
        lines.append("Source the scanner does not read (no nodes or facts come from it), by language and folder:")
        lines += [f"- {x['lang']} — {_plural(x['files'], 'file', 'files')}: {', '.join(x['folders'])}" for x in langs]
        lines.append("")
    if deps:
        lines.append("Deployables whose source is mostly not scanned: each is still a service, its relations read "
                     "from its code and config and `inferred` (SKILL.md § Deployables, not folders):")
        for d in deps:
            how = [f"compose service `{svc}` in {f}" for svc, f in d["compose"]] \
                + [f"Dockerfile `{f}`" for f in d["dockerfiles"]]
            missed = ", ".join(f"{lang} {n}" for lang, n in d["unscanned"])
            lines.append(f"- deployable `{d['folder']}` ({'; '.join(how)}) — {_plural(d['scanned'], 'file', 'files')} "
                         f"scanned; " + (f"not scanned: {missed}" if missed else "no source the scanner reads"))
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
    lines += _unscanned_lines(s.get("unscanned") or {})
    if defined := s.get("sql_files"):
        lines += [f"## Tables defined in SQL files — {len(defined)}", "",
                  "`CREATE TABLE` in `.sql` files (migrations, schemas): tables that exist whatever the code shows; "
                  "name them in the map where code reads or writes them:"]
        lines += [f"- {d['table']} ({d['file']}:{d['line']})" for d in defined] + [""]
    names = {n["id"]: n["name"] for n in s["nodes"]}
    for m in s["modules"]:
        files = [f for f, i in s["files"].items() if i["module"] == m["id"]]
        lines.append(f"## {m['id']} ({m['lang']}, {m['build']}, {len(files)} files)")
        routes_, clients, sinks, reads, writes, urls, envs = [], [], set(), set(), set(), set(), set()
        implemented: list[str] = []
        tables, queues = [], []
        grpc_ends: dict[tuple[str, str], list[str]] = {}
        dags, wfs, refs, mounts = [], [], [], []
        for f in files:
            ff = s["facts"][f]
            routes_ += [f"{r['method']} {r['path']} → {r['handler']} ({f}:{r['line']})" for r in ff["routes"]]
            mounts += [f"{x['path']}" + (f" → {x['target']}" if x["target"] else "") + f" ({f}:{x['line']}"
                       + (f", composed onto {_plural(x['composed'], 'route', 'routes')})" if x.get("composed") else ")")
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
            implemented += [" ".join([i["class"]] + ([f"extends {', '.join(i['bases'])}"] if i["bases"] else [])
                                     + ([i["annotation"]] if i["annotation"] else [])
                                     + [f"[{', '.join(i['methods'])}]", f"({f}:{i['line']})"])
                            for i in ff.get("implemented", [])]
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
                            ("framework-implemented interfaces", sorted(implemented)),
                            ("grpc servers", grpc_s), ("grpc clients", grpc_c), ("dags", dags),
                            ("flyte workflows", wfs), ("reference tasks", refs), ("sinks", sorted(sinks)),
                            ("sql reads", sorted(reads)), ("sql writes", sorted(writes)),
                            ("tables (patterns)", [_table_line(t, names) for t in sorted(tables)]),
                            ("in-process queues", queues),
                            ("url literals", sorted(urls)), ("env keys", sorted(envs))):
            for i in range(0, len(vals), SUMMARY_CHUNK):   # a long list on several lines, each with its label
                lines.append(f"- **{label}:** " + "; ".join(vals[i:i + SUMMARY_CHUNK]))
        lines.append("")
    rpcs: dict[tuple[str, str], list[str]] = {}   # one line per key and shape, with every .proto that declares it
    for p in s.get("proto", []):
        for svc in p["services"]:
            for r in svc["rpcs"]:
                rpcs.setdefault((r["key"], proto.describe(r)), []).append(f"{p['file']}:{r['line']}")
    if rpcs:
        lines.append("## Proto services (gRPC protocol keys)")
        lines += [f"- {key}: {shape} ({', '.join(at)})" for (key, shape), at in rpcs.items()]
        lines.append("")
    if s["unassigned"]:
        lines.append(f"Unassigned files (no module): {', '.join(s['unassigned'])}")
    if s.get("excluded"):
        shown = ", ".join(s["excluded"][:30]) + (" …" if len(s["excluded"]) > 30 else "")
        lines.append(f"Excluded files ({len(s['excluded'])}): {shown}")
    if s.get("generated"):
        lines.append(f"Generated files, scanned for their data types and routes only ({len(s['generated'])}): "
                     + ", ".join(s["generated"]))
    if s["skipped"]:
        lines.append(f"Skipped files: {s['skipped']}")
    errs = [f for f, i in s["files"].items() if i["parse_error"]]
    if errs:
        lines.append(f"Files with parse errors (nodes may be partial): {', '.join(errs)}")
    return "\n".join(lines) + "\n"
