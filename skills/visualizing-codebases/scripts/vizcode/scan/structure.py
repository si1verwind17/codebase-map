"""Structure pass: committed tree -> structure.json (nodes, uses-code relations, per-file facts)."""
from __future__ import annotations

import bisect
import fnmatch
import json
import posixpath
import os
import re
import signal
import tempfile
import threading
import time
import tomllib
from pathlib import Path, PurePosixPath

from .. import SCANNER_VERSION, SCHEMA_VERSION, gitsrc, ids, readme
from . import (constructors, facts, gateways, generated, proto, queue_use, routes, sqlfiles, stack, typelinks,
               unscanned, wrappers)
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


PY_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def python_dependencies(root: Path) -> set[str]:
    """The import-style names (lower case, `-` and `.` as `_`) of the libraries the repo's Python dependency files
    declare: `requirements*.txt`/`.in` lines and pyproject.toml's project and Poetry dependencies."""
    out: set[str] = set()
    for p in [*root.glob("requirements*.txt"), *root.glob("requirements*.in"), *root.glob("*/requirements*.txt")]:
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.lstrip().startswith(("#", "-")) and (m := PY_REQUIREMENT.match(line)):
                out.add(m.group(1))
    for p in [root / "pyproject.toml", *root.glob("*/pyproject.toml")]:
        try:
            doc = tomllib.loads(p.read_text(encoding="utf-8", errors="replace")) if p.is_file() else {}
        except tomllib.TOMLDecodeError:
            continue
        deps = (doc.get("project") or {}).get("dependencies") or []
        out.update(m.group(1) for d in deps if isinstance(d, str) and (m := PY_REQUIREMENT.match(d)))
        poetry = ((doc.get("tool") or {}).get("poetry") or {}).get("dependencies") or {}
        out.update(k for k in poetry if isinstance(k, str) and k.lower() != "python")   # the interpreter, no library
    return {re.sub(r"[-.]", "_", d.lower()) for d in out}


def _internal(results: dict[str, dict], file_mod: dict[str, str], mod_by_id: dict[str, dict],
              names: dict[str, dict[str, str]], protos: list[dict], aliases: set[str],
              py_deps: set[str] = frozenset()) -> dict[str, set[str]]:
    """Language -> import prefixes that name the repo's own code: packages, Python dotted names, module names,
    tsconfig path aliases, Rust `mod` names. A Python file stem or folder named like a declared dependency
    (`py_deps`: `app/celery.py` beside a `celery` requirement) is no own name: a bare import of it is the library."""
    scopes: dict[str, set[str]] = {scope: set(n) for scope, n in names.items()}
    jvm = scopes.setdefault("jvm", set())
    for f, r in results.items():
        if pkg := _declared_package(f, r, mod_by_id[file_mod[f]]):
            for scope in _scopes(_lang(f)):
                scopes.setdefault(scope, set()).add(pkg)
        if f.endswith(".py"):
            jvm.add(py_adapter.dotted_names(mod_by_id[file_mod[f]], f)[0])
            jvm.update(x for x in (Path(f).stem, *Path(f).parent.parts) if x.lower() not in py_deps)
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


GO_PACKAGE = re.compile(r"^package\s+(\w+)", re.M)
PATTERN_SECONDS = 60   # one file's pattern pass; longer means a regex that backtracks without end


class PatternTimeout(Exception):
    pass


class _time_limit:
    """Raise PatternTimeout in the block after `seconds` (a regex match is interruptible); a no-op off the main
    thread or without SIGALRM."""
    def __init__(self, seconds: float):
        self.on = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
        self.seconds = seconds

    def __enter__(self):
        if self.on:
            self.old = signal.signal(signal.SIGALRM, self._raise)
            self.outer = signal.setitimer(signal.ITIMER_REAL, self.seconds)[0]   # a caller's own timer, if any
            self.start = time.monotonic()
        return self

    def __exit__(self, *exc):
        if self.on:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, self.old)
            if self.outer:   # put it back, less the time this block took
                signal.setitimer(signal.ITIMER_REAL, max(self.outer - (time.monotonic() - self.start), 0.001))
        return False

    def _raise(self, *_):
        raise PatternTimeout(f"the patterns ran over {self.seconds:g} s: a stack.yaml regex that backtracks "
                             "(a nested quantifier such as `(\\w+\\s*)+`)?")


def _rust_module(f: str) -> tuple[str, ...]:
    """A Rust file's module path in its crate: `src/db/users.rs` -> (db, users); `mod.rs`, `lib.rs`, `main.rs` are
    their folder's module."""
    parts = f.split("/")
    parts = parts[len(parts) - 1 - parts[::-1].index("src") + 1:] if "src" in parts else parts
    parts[-1] = parts[-1].removesuffix(".rs")
    return tuple(parts[:-1] if parts[-1] in ("mod", "lib", "main") else parts)


def _rust_use_path(target: str, here: tuple[str, ...]) -> tuple[str, ...]:
    """The crate module path a `use` path names: `crate::a::b`, `super::b`, `self::b`, and an unprefixed `a::b` as a
    child module of `here` (when it is another crate, nothing there matches)."""
    segs = target.split("::")
    if segs[0] == "crate":
        return tuple(segs[1:])
    base = list(here)
    while segs and segs[0] in ("super", "self"):
        if segs.pop(0) == "super":
            base = base[:-1]
    return tuple(base + segs)


def _rehome_impls(results: dict[str, dict], file_mod: dict[str, str], reg: ids.IdRegistry) -> None:
    """A Rust `impl X for T` in a file that does not declare `T` joins the `T` its `use` lines name (`use
    super::T`, `use crate::db::T`, else a module or glob import holding one `T`); with none, it keeps its own class.
    Its methods are re-identified under that class, every id the file's facts hold with them; a method whose
    name and arity another file also gives that class takes the file's name (`#handle/2~users`), so one file's
    impls never renumber another's."""
    declared: dict[tuple[str, tuple[str, ...], str], dict] = {}   # (module id, rust module, name) -> class
    for f, r in results.items():
        if Path(f).suffix == ".rs":
            for n in r["nodes"]:
                if n["kind"] == "class" and n.get("parent") and not n["name"].startswith("new "):
                    declared.setdefault((file_mod[f], _rust_module(f), n["name"]), n)
    module_files: dict[tuple[str, tuple[str, ...]], list[str]] = {}
    for f in results:
        if Path(f).suffix == ".rs":
            module_files.setdefault((file_mod[f], _rust_module(f)), []).append(f)

    def found(mid: str, here: tuple[str, ...], imports: list[dict], name: str, seen: set) -> dict | None:
        """The struct `name` the `use` lines of module `here` bring in: a named one, else through a module or glob
        `use`; a module that only re-exports it (`pub use self::model::Record`) is followed, each module once per
        lookup (`seen`), so a cycle or a wide glob prelude ends."""
        named, held = [], []
        for imp in imports:
            path = _rust_use_path(imp["target"], here)
            if path and path[-1] == name:
                named.append(path[:-1])
            elif not path or path[-1][:1].islower():
                held.append(path)
        for paths in (named, held):
            hits: dict[str, dict] = {}
            for p in paths:
                if (c := declared.get((mid, p, name))) is not None:
                    hits[c["id"]] = c
                elif p not in seen:
                    seen.add(p)
                    for g in module_files.get((mid, p), []):
                        if (c := found(mid, p, results[g]["imports"], name, seen)) is not None:
                            hits[c["id"]] = c
            if hits:
                return next(iter(hits.values())) if len(hits) == 1 else None
        return None

    plans: dict[str, list[tuple[dict, dict]]] = {}   # file -> (attached class, target class)
    for f, r in sorted(results.items()):
        if Path(f).suffix != ".rs" or not r.get("attached"):
            continue
        for a in r["attached"]:
            if (target := found(file_mod[f], _rust_module(f), r["imports"], a["name"], {_rust_module(f)})) is not None:
                plans.setdefault(f, []).append((a, target))
    # (target, name/arity) given by more than one file: those methods carry their file's name
    givers: dict[tuple[str, str], set[str]] = {}
    for f, r in results.items():
        if Path(f).suffix == ".rs":
            for n in r["nodes"]:
                if n["kind"] == "method" and n.get("parent"):
                    givers.setdefault((n["parent"], re.sub(r"~\d+$", "", n["id"]).rsplit("#", 1)[-1]), set()).add(f)
    for f, pairs in plans.items():
        for a, target in pairs:
            for n in results[f]["nodes"]:
                if n.get("parent") == a["id"] and n["kind"] == "method":
                    givers.setdefault((target["id"], re.sub(r"~\d+$", "", n["id"]).rsplit("#", 1)[-1]), set()).add(f)
    renames: dict[str, dict[str, str]] = {}   # every class's count first: a walk below copies a file's dicts
    for f, pairs in plans.items():
        r = results[f]
        moved = renames.setdefault(f, {})
        stem = Path(f).parent.name if Path(f).stem in ("mod", "lib", "main") else Path(f).stem
        for a, target in pairs:
            target["metrics"]["methods"] = target["metrics"].get("methods", 0) + a["metrics"]["methods"]
            r["attached"].remove(a)
            moved[a["id"]] = target["id"]
            for n in r["nodes"]:   # its methods in source order, each claiming its id under the class
                if n.get("parent") == a["id"] and n["kind"] == "method":
                    base = re.sub(r"~\d+$", "", n["id"])[len(a["id"]):]
                    shared = len(givers.get((target["id"], base.lstrip("#")), ())) > 1
                    moved[n["id"]] = reg.claim(target["id"] + base + (f"~{stem}" if shared else ""))
    for f, moved in renames.items():
        r = results[f]
        olds = sorted(moved, key=len, reverse=True)

        def swap(s: str) -> str:
            for o in olds:
                if s == o or (s.startswith(o) and s[len(o)] in ".#/:"):
                    return moved[o] + s[len(o):]
            return s

        def walk(v):
            if isinstance(v, str):
                return swap(v)
            if isinstance(v, list):
                return [walk(x) for x in v]
            if isinstance(v, tuple):
                return tuple(walk(x) for x in v)
            if isinstance(v, dict):
                return {walk(k): walk(x) for k, x in v.items()}
            return v

        for k in list(r):
            r[k] = walk(r[k])


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


# a Spring Data repository's base, its first type argument the entity it serves
REPOSITORY_BASE = re.compile(r"\b(?:Jpa|Crud|PagingAndSorting|ListCrud|ListPagingAndSorting|Mongo|ReactiveCrud|"
                             r"ReactiveMongo|R2dbc|Coroutine(?:Crud|Sorting))?Repository\s*<\s*([A-Z]\w*)")


def _repository_entities(r: dict, text: str) -> dict[str, str]:
    """Each repository interface of a file with the entity its base names (`interface OrderRepository extends
    JpaRepository<Order, Long>` -> Order): read from the class's header, which the supers keep without type
    arguments."""
    lines = text.split("\n")
    out = {}
    for cid, bases in r.get("supers", []):
        if any(b.split(".")[-1].endswith("Repository") for b in bases):
            node = next((n for n in r["nodes"] if n["id"] == cid), None)
            head = "\n".join(lines[node["line"] - 1:node["line"] + 3]) if node else ""
            if (m := REPOSITORY_BASE.search(head.split("{", 1)[0])) is not None:
                out[cid] = m.group(1)
    return out


def _grpc_text(text: str, r: dict, lang: str, file_id: str | None = None) -> list[dict]:
    """The gRPC ends of proto.text_ends in one file's source, each with its line and the method (else class) it
    sits in, else (an end at the file's top: `server.addService(..)`) `file_id`; JavaScript and TypeScript
    `new <pkg>.<S>(` only in a file that imports a gRPC library."""
    js = lang in ("javascript", "typescript") and any("grpc" in i["target"] for i in r["imports"])
    spans = _spans(r, "method") + _spans(r, "class")
    out = []
    for side, name, pos in proto.text_ends(text, js):
        line = text.count("\n", 0, pos) + 1
        inside = [s for s in spans if s[0] <= line <= s[1]]
        if inside or file_id:
            out.append({"side": side, "name": name, "line": line,
                        "in": min(inside, key=lambda s: s[1] - s[0])[2] if inside else file_id})
    return out


def _bases(r: dict) -> list[tuple[str, list[str]]]:
    return list(r.get("bases", [])) + list(r.get("supers", []))


def _bound_names(imports: list[dict]) -> list[str]:
    """Every name an import may bind in its file: each segment of the target (`import a.b` binds `a`, Go binds the
    last path segment), its alias, the names it lists and their renames."""
    out: set[str] = set()
    for imp in imports:
        out |= {s for s in re.split(r"[^\w$]+", imp["target"]) if s}
        out |= {v for v in (imp.get("as"), imp.get("default")) if isinstance(v, str)}
        out |= {v for v in imp.get("names") or [] if isinstance(v, str)}
        out |= {k for k in imp.get("renames") or {} if isinstance(k, str)}
        out |= {v for v in (imp.get("renames") or {}).values() if isinstance(v, str)}
    return sorted(out)


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


def _rpc_spellings(rpc: str) -> set[str]:
    """How code calls an rpc on its stub: `GetProduct`, `getProduct`, `get_product`, `GetProductAsync`."""
    lower = rpc[:1].lower() + rpc[1:]
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", rpc).lower()
    return {rpc, lower, snake, rpc + "Async", lower + "Async"}


SELF_NAMES = {"self", "this", "cls", "base", "super"}
# a name bound to a stub a constructor makes: `c := pb.NewCartClient(conn)`, `self.stub = cart_pb2_grpc.CartStub(ch)`,
# `var client = new Cart.CartClient(channel)`, a struct field `cartClient: pb.NewCartClient(conn)`
STUB_BOUND = re.compile(r"(?:(?:self|this)\s*\.\s*)?([A-Za-z_]\w*)\s*(?::=|=|:)\s*(?:await\s+)?(?:new\s+)?"
                        r"((?:[\w$]+\.)*\w*(?:Client|Stub)|(?:[\w$]+\.)*\w+Grpc\.new(?:Blocking|Future)?Stub)\s*[(<]")
# `new proto.cart.v1.CartService(addr, creds)` (grpc-js): a client made by the service's own name
STUB_NEW = re.compile(r"(?:(?:self|this)\s*\.\s*)?([A-Za-z_]\w*)\s*(?::=|=)\s*new\s+(?:[\w$]+\.)+(\w+)\s*\(")
# a field or parameter declared with a stub type: `private readonly CartService.CartServiceClient _client;`,
# `CartServiceBlockingStub stub)`
STUB_DECLARED = re.compile(r"((?:[\w$]+\.)*\w*(?:Client|Stub))\s+(_?[A-Za-z]\w*)\s*[;=),]")


# a language's file that stands for its folder's module
BARRELS = {".py": ("__init__",), ".rs": ("mod",),
           **{s: ("index", "mod") for s in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")}}


def _grpc_call_sites(file_facts: dict[str, dict], file_mod: dict[str, str], nodes: list[dict],
                     results: dict[str, dict], generated_files: set[str]) -> None:
    """A client end where a stub is made names every rpc of its service; the calls of an rpc on that stub are the
    requests, each a client end with that rpc's key alone in the method making it. A call is on the stub when its
    value is bound in its file to the service's stub constructor (`c := pb.NewCartClient(conn)`), typed with the
    service's client or stub (an injected `CartClient client`), is that constructor's own result
    (`pb.NewCartClient(conn).GetCart(..)`), or is named after the service and as a stub (`cartSvcClient`); a call on a
    value bound to none of these (`conf.get(..)`, `redis_client.get(..)`, the repo's own `basketService`) is none, and
    so is a constructor or type naming a class the repo writes itself (its own `SparkConnectClient` wrapper).
    A service with such calls keeps no end at the stub; with none, the stub's end stays, every rpc listed."""
    by_module: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for f, ff in file_facts.items():
        for g in ff.get("grpc", []):
            if g["side"] == "client" and g["keys"]:
                by_module.setdefault((file_mod[f], g["service"]), []).append((f, g))
    by_id = {n["id"]: n for n in nodes}
    camel = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
    written = {n["name"] for n in nodes if n["kind"] == "class" and n.get("file") not in generated_files}

    def types_of(mid: str, value: str) -> list[str]:
        """The declared types of the caller's parameter, or its class's field or constructor parameter, `value`."""
        m = by_id.get(mid, {})
        owner = by_id.get(m.get("parent") or "", {})
        held = ((m.get("signature") or {}).get("params") or []) + (owner.get("fields") or []) \
            + ((owner.get("ctor") or {}).get("params") or [])
        return [p.get("type") or "" for p in held if p.get("name") == value.lstrip("_") or p.get("name") == value]

    by_service: dict[str, list[tuple[str, dict]]] = {}
    for (mod, svc), ends in by_module.items():
        by_service.setdefault(svc, []).extend(ends)

    def stub_pattern(svc: str) -> re.Pattern:
        stem = re.sub(r"Service$", "", svc)
        return re.compile(rf"(?:New)?(?:{re.escape(svc)}|{re.escape(stem)}(?:Service)?)(?:Blocking|Future)?(?:Client|Stub)"
                          rf"|{re.escape(svc)}Grpc\.new(?:Blocking|Future)?Stub")
    patterns = {svc: stub_pattern(svc) for svc in by_service}
    defined = {n["name"] for n in nodes if n["kind"] == "method"}

    # where each class the repo writes lives, as a qualifier would name it: a Go package (`httpc`, by its folder or
    # its declared name), a Python module (`wrappers`), a JVM or C# package or outer class (`com.acme`, `Outer`)
    written_at: dict[str, set[str]] = {}
    for n in nodes:
        if n["kind"] == "class" and n["name"] in written and n.get("file") not in generated_files and n.get("file"):
            p = Path(n["file"])
            if p.suffix == ".go":
                at = {p.parent.name, results.get(n["file"], {}).get("go_package") or ""}
            else:
                pkg = n["id"].split("::", 1)[-1].rsplit(n["name"], 1)[0].rstrip("./#")
                stem = p.stem
                if p.stem in BARRELS.get(p.suffix, ()):   # `wrappers/index.ts`, `fakes/__init__.py`: named by the folder
                    # the file's own segment, the last one so named (`app.fakes.__init__.Outer`, `src/index.index`)
                    if own_seg := list(re.finditer(rf"(?:^|[./]){re.escape(p.stem)}(?=[./]|$)", pkg)):
                        pkg = pkg[:own_seg[-1].start()] + pkg[own_seg[-1].end():]
                    stem = p.parent.name
                at = {stem if p.suffix == ".py" else "", re.split(r"[./]", pkg)[-1]}
            written_at.setdefault(n["name"], set()).update(at - {""})

    def own(x: str) -> bool:
        """A constructor or type naming a class the repo writes: bare (`RetryingStub(..)`, Go `NewCartClient(..)` of
        its own package) or qualified by where it lives (`*httpc.CartClient`, `com.acme.CartClient`); one qualified by
        another module (`pb.NewCartClient`, `legacy_pb2_grpc.LegacyStub`) is that module's."""
        q, _, name = x.rpartition(".")
        name = re.sub(r"^New(?=[A-Z])", "", name)
        return name in written and (not q or re.split(r"[./]", q)[-1] in written_at.get(name, ()))

    def generated_stub(ctor: str) -> bool:
        """A constructor shaped like a generated stub's (`legacy_pb2_grpc.LegacyStub`, `pb.NewStoreClient`,
        `StoreGrpc.newBlockingStub`), not a function the repo defines (`self.opStub(op)`)."""
        last = ctor.rsplit(".", 1)[-1]
        return last not in defined and not own(ctor) and (bool(re.search(r"\w+Grpc\.new\w*Stub$", ctor))
                                        or (last[:1].isupper() and bool(re.search(r"(?:Client|Stub)$", last))))
    for svc, ends in by_service.items():
        spell = {s: k for k in ends[0][1]["keys"] for s in _rpc_spellings(k.rsplit("/", 1)[-1])}
        stem = re.sub(r"Service$", "", svc)
        stub_name = patterns[svc]

        def made(x: str) -> bool:
            """The service's generated stub constructor or type (`NewCartServiceClient`, `CartStub`,
            `CartServiceGrpc.newBlockingStub`, `CartServiceBlockingStub`), never a class the repo writes itself."""
            last = x.rsplit(".", 1)[-1]
            return bool(stub_name.fullmatch(x) or stub_name.fullmatch(last)) and not own(x)
        words = {w.lower() for w in camel.findall(stem)}
        sites = []
        for f, ff in file_facts.items():
            held = results.get(f, {}).get("stub_bound", [])
            bound = {name for name, ctor in held if made(ctor) or ctor == svc}
            # a name bound to another generated stub (`self.store_stub = StoreStub(ch)`, a service the repo has no
            # proto of too); a helper of the repo's returning this one (`stub_with_op = self.opStub(op)`) is none
            others = {name for name, ctor in held if name not in bound and generated_stub(ctor)}
            for c in ff["calls"]:
                parts = re.split(r"\.|::|->", re.sub(r"\([^()]*\)", "", c["callee"]))
                if len(parts) < 2 or parts[-1] not in spell or not c.get("in"):
                    continue
                value = parts[-2]
                said = {w.lower() for w in camel.findall(value)}
                stubby = bool(said & {"client", "grpc", "stub"})
                if not (value in bound or made(value)
                        or any(made(w) for t in types_of(c["in"], value) for w in re.findall(r"[\w.]+", t))
                        or (stubby and words and words <= said)
                        or (said & {"grpc", "stub"} and bound and value not in others)):   # `self._stub` with
                    # `self._internal_stub = CartStub(..)` in the file, never `self.store_stub` bound to another
                    continue
                sites.append((f, {"side": "client", "service": svc, "keys": [spell[parts[-1]]], "in": c["in"],
                                  "line": c["line"]}))
        # a module's stub end gives way to its own calls; a factory's (`NewTrainerClient`, a function returning the
        # stub) to calls anywhere; a module whose calls the scan cannot see keeps its end
        reached = {file_mod[f] for f, _ in sites}

        def factory(mid: str) -> bool:
            """A function returning the service's stub (`func NewTrainerClient(..) trainer.TrainerServiceClient`)."""
            returns = (by_id.get(mid, {}).get("signature") or {}).get("returns") or ""
            return any(made(w) for w in re.findall(r"[\w.]+", returns))
        stubs = {id(g) for f, g in ends if file_mod[f] in reached or (sites and factory(g["in"]))}
        for f in {f for f, _ in ends}:
            file_facts[f]["grpc"] = [g for g in file_facts[f]["grpc"] if id(g) not in stubs]
        for f, g in sites:
            if g not in file_facts[f]["grpc"]:
                file_facts[f]["grpc"].append(g)
        for f in {f for f, _ in sites}:
            file_facts[f]["grpc"].sort(key=lambda e: e["line"])


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
    """Create the file node of a generic-walker file whose route handler, table, queue site or request is the file
    itself (an inline function, a file of no functions), as the walker creates it on a top-level function; a file
    node already made is reused. Runs after _resolve_handlers (a route whose handler name resolves needs none) and
    again after wrappers.find, for requests."""
    facts = [x for x in (*r["routes"], *r["tables"], *r.get("queues", []), *r.get("clients", []), *r.get("jobs", []),
                         *r.get("grpc_text", []))   # (a gRPC end at the file's top: `server.addService(..)`)
             if NEW_FILE_NODE in (x.get("handler"), x.get("in"))]
    if not facts:
        return
    if (node := next((n for n in r["nodes"] if n["kind"] == "file"), None)) is None:
        pid, name = ids.package_id(module_id, r["package"]), Path(f).name
        node = {"id": reg.claim(f"{pid}{name}"), "kind": "file", "parent": pid, "name": name, "lang": lang,
                "file": f, "line": 1, "visibility": "public", "metrics": {"loc": loc, "methods": 0}}
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
    # a class-only pattern on a function is another framework's decorator: gone before dedupe keeps one of the two
    decls = _Decls(r["nodes"]) if any(x["framework"] in CLASS_ROUTES for x in found) else None
    found = [x for x in found if x["framework"] not in CLASS_ROUTES or decls.decorated(x) is not None]
    return _dedupe(st.patterns, lang, found, "routes", "framework", ("method", "path", "handler"), r)


class _Decls:
    """A file's classes and methods by line, built once, for `decorated`."""
    def __init__(self, nodes: list[dict]):
        self.decls = sorted((n["line"], n["kind"], n["id"], n.get("parent")) for n in nodes
                            if n["kind"] in ("class", "method"))
        self.lines = [d[0] for d in self.decls]
        self.spans = [(n["line"], n["line"] + n["metrics"].get("loc", 1), n["id"]) for n in nodes
                      if n["kind"] in ("class", "method")]
        self.file = next((n["id"] for n in nodes if n["kind"] == "file"), None)

    def decorated(self, route: dict) -> str | None:
        """The class a route decorator sits on: the next declaration below it, when that is a class in the
        decorator's own scope (the innermost class or method around it, else the file); a class nested in a function
        has no node, so the next one is another scope's."""
        i = bisect.bisect_right(self.lines, route["line"])
        if i >= len(self.decls) or self.decls[i][1] != "class":
            return None
        line = route["line"]
        around = [s for s in self.spans if s[0] <= line < s[1]]
        scope = max(around)[2] if around else self.file
        return self.decls[i][2] if self.decls[i][3] == scope else None


def _beside_code_rules(r: dict, found: list[dict]) -> list[dict]:
    """The pattern routes a code rule (FastAPI, tapir) has not already read: same method and handler, and the code
    rule's path the pattern's or ending in it (the rule joined the router's prefix, the pattern did not); each
    dropped one is noted in r["deduped"] as a duplicate of that rule."""
    seen = [(x["method"], x["path"], x["handler"], x.get("framework")) for x in r["routes"]]
    kept = []
    for x in found:
        if (by := next((fw for m, p, h, fw in seen if (m, h) == (x["method"], x["handler"])
                        and (p == x["path"] or p.endswith("/" + x["path"].strip("/")))), None)) is not None:
            r.setdefault("deduped", []).append(("routes", x["framework"], by))
        else:
            kept.append(x)
    return kept


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
        if qualify and text[m.end():] in ("", "::class", ".as_view"):   # a class named as handler keeps its suffix
            segs = _segments(target)
            return "/".join(segs + ([member] if segs[-1:] != [member] else [])) + text[m.end():]
        return m.group(1) + member + text[m.end():]
    for c in r["calls"]:
        c["callee"] = plain(c["callee"])
    for route in r["routes"]:
        for key in ("handler_name", "handler_class"):
            if route.get(key):   # a class named as the handler (`Foo::class`) keeps its import's namespace too
                route[key] = plain(route[key], key == "handler_class" or route[key].endswith(("::class", ".as_view")))
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
        if name in (imp.get("names") or []):
            hit = _relative_file(f, imp["target"], results) if imp["relative"] else None
            out.append(hit or tuple(parts[-1:]))
        elif parts and parts[-1] == name and len(parts) > 1:
            out.append(tuple(parts[-2:-1]))
        elif qualifier and parts and qualifier in (imp.get("as"), parts[-1]):
            out.append(tuple(parts[-1:]))
    return out


def _ends_with(f: str, segs: list[str]) -> bool:
    """A file whose module path (`shop/views.py`, or its folder for a package) ends with the dotted segments."""
    own = Path(f).with_suffix("").parts
    return any(len(p) >= len(segs) and list(p[-len(segs):]) == segs for p in (own, own[:-1]))


def _qualified(r: dict, cls: str) -> str:
    """A bare class name the file imports, written with the namespace it is imported from (`ScrobbleController`
    -> `App/Http/Controllers/API/ScrobbleController`), so two same-named classes are told apart."""
    if len(_segments(cls)) > 1:
        return cls
    for imp in r["imports"]:
        renamed = imp.get("renames") or {}
        # the names the file uses for this import: a member renamed away (`use X as AdminX`) is not one
        local = {*(n for n in imp.get("names") or [] if n not in renamed.values() or n in renamed), *renamed}
        if cls in local and not imp["relative"]:
            member = renamed.get(cls, cls)
            return "/".join(_segments(imp["target"]) + [member])
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


def _file_level_handlers(r: dict, reg: ids.IdRegistry) -> None:
    """A route registered at a file's top level with an inline handler (`router.post("x", auth(), async (ctx) =>
    {..})`) has the file as handler: the outermost lambda among the call's own arguments becomes a method node of the
    file named after the route (`post_x`), the route's handler, and the calls, strings, tables, queues, jobs and
    requests inside it move to it."""
    file_node = next((n for n in r["nodes"] if n["kind"] == "file"), None)
    if file_node is None:
        return
    for route in r["routes"]:
        # one of the call's own arguments: a lambda starting from the route's line to the line its call closes on
        if "call_end" not in route:
            continue
        here = [x for x in r.get("lambdas", []) if x["in"] is None
                and route["line"] <= x["start"] <= route["call_end"]]
        if route["handler"] != file_node["id"] or not here:
            continue
        lam = min(here, key=lambda x: (x["start"], -x["end"]))
        if lam.get("node"):   # one handler for several methods (`route({method: ['GET', 'POST'], ..})`)
            route["handler"] = lam["node"]
            continue
        words = [w for w in re.split(r"[^A-Za-z0-9]+", route["path"]) if w]
        name = "_".join([route["method"].lower(), *words]) or route["method"].lower()
        nid = reg.claim(ids.method_id(file_node["id"], name, 0))
        r["nodes"].append({"id": nid, "kind": "method", "parent": file_node["id"], "name": name,
                           "lang": file_node["lang"], "file": file_node["file"], "line": lam["start"],
                           "visibility": "private", "metrics": {"loc": lam["end"] - lam["start"] + 1},
                           "signature": {"params": [], "returns": None}})
        file_node["metrics"]["methods"] = file_node["metrics"].get("methods", 0) + 1
        for group in ("calls", "strings", "tables", "queues", "jobs", "clients"):
            for x in r.get(group, []):
                if x.get("in") in (None, file_node["id"]) and lam["start"] <= x["line"] <= lam["end"] \
                        and not (group == "calls" and x["line"] == route["line"] and x.get("in") is None
                                 and x["callee"].rsplit(".", 1)[-1].lower() == route["method"].lower()):
                    x["in"] = nid
        lam["node"] = nid
        route["handler"] = nid


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
    for group in ("calls", "strings", "tables", "queues", "jobs"):
        for x in r.get(group, []):
            if x.get("in") == outer["id"] and nested["start"] <= x["line"] <= nested["end"]:
                x["in"] = nid
    for other in r["nested"]:
        if other is not nested and other["in"] == outer["id"] and nested["start"] <= other["line"] <= nested["end"]:
            other["in"] = nid
    nested["node"] = nid
    return nid


def _python_file(f: str, target: str, results: dict[str, dict]) -> str | None:
    """The scanned file a Python import target names: `.x`/`..x` from f's folder, else the one file whose path ends
    in the dotted name (`a.b` -> `.../a/b.py` or `.../a/b/__init__.py`), the closest to f when several do."""
    if target.startswith("."):
        dots = len(target) - len(target.lstrip("."))
        base = Path(f).parent
        for _ in range(dots - 1):
            base = base.parent
        rest = [x for x in target.lstrip(".").split(".") if x]
        stems = [(base / Path(*rest)).as_posix()] if rest else [base.as_posix()]
        found = [g for s in stems for g in (s + ".py", s + "/__init__.py") if g in results]
        return found[0] if found else None
    tail = "/" + target.replace(".", "/")
    found = [g for g in results if g.endswith(".py") and ("/" + g[:-3]).removesuffix("/__init__").endswith(tail)]
    if len(found) > 1:
        found.sort(key=lambda g: -len(os.path.commonpath([g, f])))
    return found[0] if found else None


def _router_of(f: str, expr: str, results: dict[str, dict]) -> tuple[str, str] | None:
    """(file, variable) of the router an include_router argument names: one of f's own, or one f imports
    (`from m import router`, `from pkg import m` + `m.router`, `import pkg.m as m` + `m.router`)."""
    head, *rest = expr.split(".")
    r = results[f]
    if not rest and head in r.get("routers", {}):
        return f, head
    for imp in r["imports"]:
        names = imp.get("names") or []
        local = {**{n: n for n in names}, **{a: m for a, m in (imp.get("renames") or {}).items()}}
        if head in local:
            member = local[head]
            target = imp["target"].rstrip(".") + "." + member if imp["target"].strip(".") else imp["target"] + member
            if rest and (g := _python_file(f, target, results)) is not None:
                return g, rest[-1]
            if not rest and (g := _python_file(f, imp["target"], results)) is not None:
                return g, member
        elif not names and rest and (imp.get("as") == head or ".".join([head, *rest[:-1]]) == imp["target"]):
            if (g := _python_file(f, imp["target"], results)) is not None:   # `import a.m as m`, `import a.m`
                return g, rest[-1]
    return None


def _compose_includes(results: dict[str, dict]) -> None:
    """Join include_router prefixes onto the routes of the routers they include, across files: a route's path
    gets every including router's own prefix and include prefix, up to a router nothing includes. A router
    included in two places gives its routes once per place. An include that names a router counts its routes
    in `composed`."""
    parents: dict[tuple[str, str], list[tuple[tuple[str, str], str, dict]]] = {}
    for f, r in results.items():
        for inc in r.get("includes", []):
            if (child := _router_of(f, inc["router"], results)) is not None:   # the app may be a parameter
                parents.setdefault(child, []).append(((f, inc["app"]), inc["prefix"], inc))

    def chains(node: tuple[str, str], seen: frozenset) -> list[tuple[str, list[dict]]]:
        """(prefix above the router's own, includes passed) for each way down to `node`."""
        ups = [(p, pre, inc) for p, pre, inc in parents.get(node, []) if p not in seen]
        if not ups:
            return [("", [])]
        out = []
        for p, pre, inc in ups:
            own = results[p[0]].get("routers", {}).get(p[1], "")
            out += [(above + own + pre, incs + [inc]) for above, incs in chains(p, seen | {p})]
        return out

    for f, r in results.items():
        if not any(route.get("router") for route in r["routes"]):
            continue
        out = []
        for route in r["routes"]:
            obj = route.pop("router", None)
            ways = chains((f, obj), frozenset({(f, obj)})) if obj else [("", [])]
            for above, incs in ways:
                out.append({**route, "path": stack.normalise(above + route["path"])} if above else dict(route))
                for inc in incs:
                    inc["composed"] = inc.get("composed", 0) + 1
        r["routes"] = out


def _mount_target(f: str, target: str, results: dict[str, dict],
                  src: str = "") -> tuple[str, str | None] | None:
    """(file, exported name or None for its default export) of the router a mount in file f names through f's
    imports: `import users from './users'` + `use('/u', users)`, `{ adminRouter }`, `* as api` + `api.router`, or a
    router of f itself that routes are registered on. In
    Python, a name f imports (`register_blueprint(bp, ..)`), or a dotted module (`include("shop.api.urls")`: name
    `*`, every route of that module)."""
    if f.endswith(".py"):
        if (hit := _router_of(f, target, results)) is not None:
            return hit
        g = _python_file(f, target, results) if "." in target else None
        return (g, "*") if g else None
    head, *rest = target.split(".")
    for imp in results[f]["imports"]:
        if not imp["relative"] or (g := _relative_file(f, imp["target"], results)) is None:
            continue
        if imp.get("default") == head:
            return g, None
        renames = imp.get("renames") or {}
        if head in renames or head in (imp.get("names") or []):
            name = renames.get(head, head)
            return g, None if name == "default" else name
        if imp.get("as") == head and rest:
            return g, rest[0]
    if not rest and any(x.get("on") == head for x in results[f]["routes"] + results[f].get("mounts", [])
                        if x.get("target") or "target" not in x) \
            and len(re.findall(rf"(?<![\w$.]){re.escape(head)}\s*(?::\s*[\w<>\[\].]+\s*)?:?=(?!=)", src)) <= 1:
        return f, head   # a router of the same file bound once (`notes.get(..)`, then `app.route("/notes", notes)`)
    return None


def _imported_libraries(results: dict[str, dict], pending: dict[str, tuple[str, list[str]]]) -> dict[str, list[str]]:
    """File -> the library imports of the repo files it imports (one hop): a pattern gated on a library also runs
    on a file that reaches it through the repo's own module (`from app.extensions import db` over flask_sqlalchemy,
    a local Prisma client, a Flask-RESTX `api` object)."""
    out: dict[str, list[str]] = {}
    for f, r in results.items():
        got: list[str] = []
        for imp in r["imports"]:
            if imp["relative"]:
                g = _relative_file(f, imp["target"], results)
            elif f.endswith(".py"):
                g = _python_file(f, imp["target"], results) or next(
                    (x for n in imp.get("names") or [] if (x := _python_file(f, imp["target"] + "." + n, results))), None)
            else:
                g = None
            if g and g != f and g in pending:
                got += pending[g][1]
        if got:
            out[f] = list(dict.fromkeys(got))
    return out


def _passed_mounts(results: dict[str, dict]) -> None:
    """A mount handed to a function (`users.UsersRegister(v1.Group("/users"))`, gin, echo, chi): the routes that
    function registers on its first parameter get the mount's full prefix. The function is the one of that name
    whose folder ends in the call's qualifier (`users`), else the only one of that name; its routes are those in its
    span whose router is the parameter. The mount counts them in `composed`."""
    by_name: dict[str, list[tuple[str, dict]]] = {}
    for f, r in results.items():
        for n in r["nodes"]:
            if n["kind"] == "method":
                by_name.setdefault(n["name"], []).append((f, n))
    for f, r in results.items():
        for mt in r.get("mounts", []):
            name, full = mt.pop("passed_to", None), mt.pop("full", None)
            if not name or full is None:
                continue
            *qual, last = name.split(".")
            cands = by_name.get(last, [])
            if qual and len(cands) > 1:
                cands = [(g, n) for g, n in cands if Path(g).parent.name == qual[-1]]
            if len(cands) != 1:
                continue
            g, fn = cands[0]
            params = (fn.get("signature") or {}).get("params") or []
            if not params or not params[0].get("name"):
                continue
            param, end = params[0]["name"], fn["line"] + fn["metrics"]["loc"] - 1
            for route in results[g]["routes"]:
                if route.get("on") == param and fn["line"] <= route["line"] <= end:
                    route["path"] = stack.normalise(full + "/" + route["path"].lstrip("/"))
                    route.pop("on", None)
                    mt["composed"] = mt.get("composed", 0) + 1


def _compose_mounts(results: dict[str, dict], sources: dict[str, str] | None = None) -> None:
    """Join the prefix of a mount whose router comes from another file (`app.use('/users', usersRouter)`) onto that
    file's routes registered on the router it exports: its named export, or for the default export the file's one
    router. Mount chains compose outward across files; a router mounted in two places gives its routes once per
    place. The mount counts its routes in `composed`."""
    _passed_mounts(results)
    parents: dict[tuple[str, str], list[tuple[tuple[str, str] | None, str, dict]]] = {}
    for f, r in results.items():
        for mt in r.get("mounts", []):
            if not mt.get("target") or (hit := _mount_target(f, mt["target"], results,
                                                             (sources or {}).get(f, ""))) is None:
                continue
            g, name = hit
            ons = {x["on"] for x in results[g]["routes"] if x.get("on")} | \
                  {m["on"] for m in results[g].get("mounts", []) if m.get("on") and m.get("target")}
            var = "*" if name == "*" else name if name in ons else (
                next(iter(ons)) if name is None and len(ons) == 1 else None)
            if var is not None:
                parents.setdefault((g, var), []).append(((f, mt["on"]) if mt.get("on") else (f, "*"), mt["path"], mt))

    def chains(node: tuple[str, str], seen: frozenset) -> list[tuple[str, list[dict]]]:
        ups = [(p, pre, mt) for p, pre, mt in parents.get(node, []) if p not in seen]
        if not ups:
            return [("", [])]
        out = []
        for p, pre, mt in ups:
            above = chains(p, seen | {p}) if p is not None else [("", [])]
            out += [(a + "/" + pre.strip("/"), mts + [mt]) for a, mts in above]
        return out

    for f, r in results.items():
        out = []
        for route in r["routes"]:
            on, own = route.pop("on", None), route.pop("own_prefix", None)
            node = (f, on) if on and (f, on) in parents else (f, "*") if (f, "*") in parents else None
            ways = chains(node, frozenset({node})) if node else [("", [])]
            for above, mts in ways:
                path = route["path"]
                if own and mts and mts[-1].get("framework") == "flask-register-blueprint":
                    # `register_blueprint(bp, url_prefix="/v2")` replaces the blueprint's own `url_prefix`
                    path = stack.normalise(path[len(stack.normalise(own)):] if path.startswith(stack.normalise(own)) else path)
                out.append({**route, "path": stack.normalise(above + "/" + path.lstrip("/"))} if above
                           else {**route, "path": path})
                for mt in mts:
                    mt["composed"] = mt.get("composed", 0) + 1
        r["routes"] = out
    for r in results.values():
        for mt in r.get("mounts", []):
            mt.pop("on", None)


# patterns whose route is a class's alone: a match on a function is another framework's decorator
CLASS_ROUTES = {"flask-restx", "flask-restplus"}
# a handler naming a class: Django/Flask `View.as_view(..)`, Laravel `Foo::class`
CLASS_VIEW = re.compile(r"^((?:[\w$]+(?:\.|::|\\|/))*[A-Z][\w$]*)(\.as_view|::class)?$")
# the methods a class-based view answers each HTTP method with, and those that answer whatever the route says
VERB_METHODS = {"get": "GET", "post": "POST", "put": "PUT", "patch": "PATCH", "delete": "DELETE", "head": "HEAD",
                "options": "OPTIONS"}
INVOKE_METHODS = ("__invoke", "__call__")


def _class_routes(results: dict[str, dict]) -> None:
    """A route handled by a class (named as one: `View.as_view()`, `Foo::class`; or a route decorator on a class:
    `@ns.route('/x')` over `class Users(Resource)`, past its other decorators) is one route per HTTP-verb method the
    class or its repo bases define (`get`, `post`, ..), each its handler, when the route names no method (ANY or the
    framework's default), else the one for its verb; a class with an invoke method (`__invoke`, `__call__`) keeps
    the route's method, that method its handler. A class with neither, or a Laravel `::class` (dispatched only by
    `__invoke`), is the handler itself."""
    nodes = {n["id"]: n for r in results.values() for n in r["nodes"]}
    members: dict[str, dict[str, str]] = {}
    for n in nodes.values():
        if n["kind"] == "method" and nodes.get(n.get("parent") or "", {}).get("kind") == "class":
            members.setdefault(n["parent"], {}).setdefault(n["name"], n["id"])

    def methods_of(cid: str) -> dict[str, str]:
        out, todo, seen = {}, [cid], set()
        while todo:
            c = todo.pop(0)
            if c in seen or c not in nodes:
                continue
            seen.add(c)
            for name, mid in members.get(c, {}).items():
                out.setdefault(name, mid)
            todo += nodes[c].get("implements") or []
        return out

    for f, r in results.items():
        if not r["routes"]:
            continue
        starts = sorted((n["line"], n["kind"], n["id"]) for n in r["nodes"] if n["kind"] in ("class", "method"))
        decls = _Decls(r["nodes"]) if any(x["framework"] in CLASS_ROUTES for x in r["routes"]) else None
        out = []
        for route in r["routes"]:
            cid, form = route.pop("handler_cls", None), route.pop("handler_form", None)
            default = route.pop("method_default", False)
            if cid is None:   # a decorator on a class: the next declaration below the route, past its decorators
                below = next((s for s in starts if s[0] > route["line"]), None)
                h = nodes.get(route["handler"], {})
                if route["framework"] in CLASS_ROUTES:   # a restx class with no method of its own still takes it
                    cid = decls.decorated(route)
                elif below and below[1] == "class" and (h.get("parent") == below[2] or route["handler"] == below[2]):
                    cid = below[2]
            if cid is None:
                if route["framework"] not in CLASS_ROUTES:   # `@ns.route` decorates a Resource class, never a function
                    out.append(route)
                continue
            own = methods_of(cid)
            if invoke := next((own[m] for m in INVOKE_METHODS if m in own), None):
                out.append({**route, "handler": invoke})
                continue
            verbs = [(VERB_METHODS[m], mid) for m, mid in own.items() if m in VERB_METHODS]
            if not verbs or form == "::class":   # Laravel calls only an invokable class: no verb dispatch
                out.append({**route, "handler": cid})
                continue
            # an unnamed method (ANY, or the framework's default) is every verb the class serves; a named one only its own
            out += [{**route, "method": verb, "handler": mid} for verb, mid in sorted(verbs)
                    if route["method"] == "ANY" or default or route["method"] == verb] \
                or [route]   # a class with no method for the route's verb: the route as it was
        r["routes"] = out


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
    owner_name = {n["id"]: _segments(n["name"])[-1] for r in results.values() for n in r["nodes"] if n["kind"] == "class"}
    classes: dict[tuple[str, str], list[str]] = {}       # (module, class name) -> class ids
    any_classes: dict[str, list[str]] = {}               # class name -> class ids in every module
    members: dict[tuple[str, str], list[str]] = {}       # (class id, method name) -> method ids
    top: set[str] = set()   # classes in no namespace: a folder's package (Ruby names a module's after it), no outer class
    for f, r in results.items():
        for n in r["nodes"]:
            if n["kind"] == "class" and owner_kind.get(n.get("parent") or "") != "class" \
                    and not r["package"][:1].isupper() and not re.search(r"\.|::", n["name"]):
                top.add(n["id"])
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
            if cls and (found := _conventional_handler(cls, meth, pool, members, top)):
                route.pop("handler_name", None)
                route.pop("nested_handler", None)
                route["handler"] = found
                continue
            name = route.pop("handler_name", None) or route.pop("nested_handler", None)
            # `Users.as_view()`, `Foo::class`, or a bare class name no method has (`add_resource(Users, ..)`)
            if name and (view := CLASS_VIEW.match(name.lstrip("\\"))) and (view.group(2) or not anywhere.get(
                    _segments(view.group(1))[-1])):
                cname = _qualified(r, view.group(1))
                # imported from outside the repo (`from rest_framework_simplejwt.views import X`): no repo class
                outside = any(view.group(1) in (imp.get("names") or []) and not imp["relative"]
                              and _in_repo(f, imp, results, names) is None
                              and not any(_ends_with(g, imp["target"].split(".")) for g in results)
                              for imp in r["imports"])
                pool = [] if outside else (classes.get((file_mod[f], _segments(cname)[-1]), [])
                                           or any_classes.get(_segments(cname)[-1], []))
                if len(pool) > 1 and (outer := [x.lower() for x in _segments(cname)[:-1]]):   # told apart by namespace
                    pool = [c for c in pool if [x.lower() for x in _segments(c.split("::", 1)[-1])[:-1]][-len(outer):]
                            == outer]
                if len(pool) == 1:
                    route["handler_cls"], route["handler_form"] = pool[0], view.group(2)
                    continue
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
            if len(parts) > 1 and len(cands) > 1:   # `articles::list`: the file the qualifier names (`articles/mod.rs`)
                cands = [c for c in cands if (Path(c[0]).parent.name if Path(c[0]).stem in ("mod", "index", "__init__")
                                              else Path(c[0]).stem) == parts[-2]] or cands

            def qualified(hit: list) -> list:
                """`wrapper.X` among several of one level: the class named like the qualifier, whole or as its last
                word (`ServerInterfaceWrapper`)."""
                q = parts[-2].lower() if len(parts) > 1 else ""
                return [c for c in hit if (o := owner_name.get(parent.get(c[2]) or "", "")) and (
                    o.lower() == q or (len(q) >= 3 and o.lower().endswith(q) and o[-len(q)].isupper()))]
            if len(parts) == 1:
                cands = [c for c in cands if owner_kind.get(parent.get(c[2]) or "") == "file"] or cands
            found = None
            for level in (lambda c: c[0] == f, lambda c: c[1] == r["package"], lambda c: True):
                hit = [c for c in cands if level(c)]
                if len(hit) > 1:
                    hit = qualified(hit) or hit
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


FS_VERBS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
FS_SUFFIXES = (".ts", ".js", ".mts", ".mjs", ".tsx", ".jsx")
FS_EXPORT = re.compile(r"^\s*export\s+(?:async\s+)?(?:function\s*\*?\s*|(?:const|let|var)\s+)(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b",
                       re.M)
FS_EXPORT_LIST = re.compile(r"^\s*export\s*\{([^}]*)\}", re.M)   # `export { handler as GET, handler as POST }`
# `export default function handler(..)`, `export default handler`, `export default withAuth(handler)`; anything else
# exported by default (an arrow, `defineEventHandler(..)`) has no name: the file is the handler
FS_DEFAULT = re.compile(r"^\s*export\s+default\b(?:\s+(?:async\s+)?(?:function\s*\*?\s*([A-Za-z_$][\w$]*)"
                        r"|([A-Za-z_$][\w$]*)\s*;?\s*$|(?:[\w$.]+\(\s*)+([A-Za-z_$][\w$]*)\s*\)+\s*;?\s*$))?", re.M)
# file-system routers: the framework's package, the folder its routes sit under, and how a file there serves
FS_ROUTERS = (("next", "pages/api", "default"), ("next", "app", "route"), ("@sveltejs/kit", "routes", "server"),
              ("nuxt", "server/api", "nuxt"), ("nuxt", "server/routes", "nuxt"))


def _fs_segment(seg: str) -> str | None:
    """A file-system route segment in the key form: `[id]` and `[id=int]` -> `{id}`, a catch-all `[...slug]` or
    `[[...slug]]` -> `{slug}`; a route group `(admin)` or a parallel slot `@modal` adds none."""
    if (seg.startswith("(") and seg.endswith(")")) or seg.startswith("@"):
        return None
    if m := re.fullmatch(r"\[{1,2}(?:\.\.\.)?([A-Za-z_$][\w$]*)(?:=\w+)?\]{1,2}", seg):
        return "{" + m.group(1) + "}"
    return seg


def _package_deps(root: Path, tree: list[str]) -> dict[str, set[str]]:
    """Folder -> the dependencies its package.json names (dependencies, devDependencies, peerDependencies)."""
    out = {}
    for f in tree:
        if PurePosixPath(f).name == "package.json":
            try:
                doc = json.loads((root / f).read_text(encoding="utf-8", errors="replace"))
            except ValueError:
                doc = {}
            out[PurePosixPath(f).parent.as_posix()] = {d for k in ("dependencies", "devDependencies", "peerDependencies")
                                                        for d in ((doc.get(k) or {}) if isinstance(doc, dict) else {})}
    return out


def _file_system_routes(pkg_deps: dict[str, set[str]], results: dict[str, dict], sources: dict[str, str]) -> None:
    """Routes a framework derives from file paths, for a project whose package.json names it: Next.js `pages/api/x/
    [id].ts` (its default export, ANY) and `app/x/[id]/route.ts` (each exported verb function), SvelteKit
    `src/routes/x/+server.ts` (each exported verb), Nuxt `server/api/x/[id].get.ts` (the verb in the name, else ANY).
    The handler is the function of that name, else the file. pkg_deps: _package_deps."""
    for f, r in results.items():
        if not f.endswith(FS_SUFFIXES) or f not in sources:
            continue
        parts = PurePosixPath(f).parts
        deps = None
        for package, under, how in FS_ROUTERS:
            base = tuple(under.split("/"))
            at = next((i for i in range(len(parts) - len(base)) if parts[i:i + len(base)] == base), None)
            if at is None:
                continue
            if deps is None:   # the nearest package.json at or above the routes folder
                deps = next((pkg_deps[d] for i in range(at, -1, -1)
                             if (d := PurePosixPath(*parts[:i]).as_posix() if i else ".") in pkg_deps), set())
            if package not in deps:
                continue
            # the name without its extension; `[...nextauth].ts` keeps its dots, a Nuxt `x.get.ts` its verb apart
            folders, stem = list(parts[at + len(base):-1]), PurePosixPath(f).name.rsplit(".", 1)[0]
            verb = "ANY"
            if how == "nuxt" and (v := re.search(r"\.(get|post|put|patch|delete|head|options)$", stem)):
                stem, verb = stem[:v.start()], v.group(1).upper()
            src, verbs = sources[f], []
            if how == "route" and stem == "route" or how == "server" and stem == "+server":
                verbs = [(m.group(1), m.group(1), src.count("\n", 0, m.start()) + 1) for m in FS_EXPORT.finditer(src)]
                for m in FS_EXPORT_LIST.finditer(src):
                    for item in m.group(1).split(","):
                        local, _, public = (x.strip() for x in item.partition(" as "))
                        if (public or local) in FS_VERBS:
                            verbs.append((public or local, local, src.count("\n", 0, m.start()) + 1))
            elif how == "default" and not stem.startswith("_"):
                folders += [] if stem == "index" else [stem]
                if d := FS_DEFAULT.search(src):
                    verbs = [("ANY", d.group(1) or d.group(2) or d.group(3), src.count("\n", 0, d.start()) + 1)]
            elif how == "nuxt":
                folders += [] if stem == "index" else [stem]
                if d := FS_DEFAULT.search(src):
                    verbs = [(verb, d.group(1) or d.group(2) or d.group(3), src.count("\n", 0, d.start()) + 1)]
            if not verbs:
                break
            prefix = list(base[1:]) if how == "default" or (how == "nuxt" and base[-1] == "api") else []
            segs = [x for x in (_fs_segment(p) for p in prefix + folders) if x]
            path = stack.normalise("/".join(segs))
            seen = set()
            for method, fn, line in verbs:
                if method in seen:
                    continue
                seen.add(method)
                handler = next((n["id"] for n in r["nodes"] if n["kind"] == "method" and fn and n["name"] == fn
                                and n.get("parent", "").endswith(PurePosixPath(f).name)), None) \
                    or next((n["id"] for n in r["nodes"] if n["kind"] == "method" and fn and n["name"] == fn), None) \
                    or NEW_FILE_NODE
                r["routes"].append({"method": method, "path": path, "handler": handler, "line": line,
                                    "framework": f"{package.split('/')[-1]}-files"})
            break


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


def _conventional_handler(cls: str, meth: str, cands: list[str], members: dict, top: set[str]) -> str | None:
    """The method `meth` of the one class among cands that `cls` names (see _resolve_handlers), else None. `top`:
    the classes in no namespace (in a folder's package, not a module's or a class's)."""
    outer = [x.lower() for x in _segments(cls)[:-1]]
    if outer:   # a named namespace: the class id's package and outer-class segments end with cls's own
        cands = [c for c in cands if [x.lower() for x in _segments(c.split("::", 1)[-1])[:-1]][-len(outer):] == outer]
    elif len(cands) > 1:   # none named: the one in no namespace (`ProfilesController`, not `Api::V1::`'s)
        cands = [c for c in cands if c in top] or cands
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
    pending: dict[str, tuple[str, list[str]]] = {}   # a parsed file's language and import names, for the patterns
    skipped: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in gitsrc.export_tree(repo, commit, root):
            skipped.append({"file": name, "reason": "link points outside the repository; not extracted"})
        tree = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and not p.is_symlink())
        # the `project/` folder beside each build.sbt (a repo of samples has one per folder)
        patterns += sorted({SBT_BUILD_DIR if d == "." else f"{d}/{SBT_BUILD_DIR}" for f in tree
                            if f.endswith("/build.sbt") or f == "build.sbt"
                            for d in [PurePosixPath(f).parent.as_posix()]})
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
                sources[f] = decode(data)
                r["grpc_text"] = _grpc_text(decode(data), r, lang, _file_id(r, mod_by_id[file_mod[f]], lang))
                src_lines = decode(data).split("\n")
                hit = [i for i, x in enumerate(src_lines) if "Client" in x or "Stub" in x or "new " in x]
                # the lines that can bind a stub, and the one before each (`c =\n\tpb.NewCartClient(conn)`)
                text_ = "\n".join(src_lines[i] for i in sorted({j for i in hit for j in (i - 1, i) if j >= 0}))
                grpc_lib = any("grpc" in i["target"].lower() for i in r["imports"])
                if bound := sorted(set(STUB_BOUND.findall(text_)) | (set(STUB_NEW.findall(text_)) if grpc_lib else set())
                                   | {(n, t) for t, n in STUB_DECLARED.findall(text_)}):
                    r["stub_bound"] = [list(b) for b in bound]   # (name, constructor or type) for gRPC call sites
                if lang == "go" and (clause := GO_PACKAGE.search(decode(data))):
                    r["go_package"] = clause.group(1)   # the name its importers call it by, whatever its folder
                if lang in SPECS:
                    lines[f] = decode(data).count("\n") + 1
            except Exception as err:
                skipped.append({"file": f, "reason": f"parser failed: {type(err).__name__}: {err}"[:200]})
                continue
            results[f] = r
            pending[f] = (lang, names)
            if generated.generated(f, decode(data)):
                gen_files.append(f)
            if f.endswith(".scala"):   # kept only for `_declared`
                texts[f] = decode(data)
        _rehome_impls(results, file_mod, reg)
        hop = _imported_libraries(results, pending)
        for f, (lang, names) in list(pending.items()):
            r = results[f]
            try:   # the patterns read the source with comments and docstrings blanked
                with _time_limit(PATTERN_SECONDS):
                    names = names + hop.get(f, [])
                    data = stack.pattern_text(sources[f], lang).encode()
                    r["mounts"] = stack.find_mounts(st, lang, decode(data), names)
                    r["routes"] += _beside_code_rules(r, _pattern_routes(st, lang, data, r, mod_by_id[file_mod[f]], names))
                    if any(h["kind"] in stack.SERVER_KINDS for imp in r["imports"] for h in stack.import_sinks(st, lang, imp)):
                        r["route_like"] = [x for x in stack.route_like(decode(data), lang)
                                           if not any(a <= x["line"] <= b for a, b in _bodyless_spans(r))]
                    r["tables"] = _pattern_tables(st, lang, data, r, mod_by_id[file_mod[f]], names)
                    if repos := _repository_entities(r, sources[f]):
                        r["repositories"] = repos
                    r["untabled"] = stack.entities_without_table(r, any(
                        h["kind"] in stack.DB_KINDS for imp in r["imports"] for h in stack.import_sinks(st, lang, imp)))
                    r["queues"] = _pattern_queues(st, lang, data, r, mod_by_id[file_mod[f]], names)
                    r["jobs"] = stack.find_jobs(st, lang, decode(data), names, _spans(r, "method"), _spans(r, "class"),
                                                {n["id"]: n["name"] for n in r["nodes"]},
                                                _file_id(r, mod_by_id[file_mod[f]], lang))
                    renamed = {a: m for imp in r["imports"] for a, m in (imp.get("renames") or {}).items()}
                    for j in r["jobs"]:   # `from tasks import send as send_task`: `send_task.delay()` enqueues `send`
                        if j["side"] == "enqueue" and j["job"] in renamed:
                            j["job"] = re.split(r"\.|::|\\", renamed[j["job"]])[-1]
            except Exception as err:   # as a parse crash: the file is skipped whole
                skipped.append({"file": f, "reason": str(err) if isinstance(err, PatternTimeout)
                                else f"parser failed: {type(err).__name__}: {err}"[:200]})
                for store in (results, sources, lines, texts):
                    store.pop(f, None)
                if f in gen_files:
                    gen_files.remove(f)
        protos = []
        for p in sorted(root.rglob("*.proto")):
            f = p.relative_to(root).as_posix()
            if (p.is_file() and not p.is_symlink() and not excluded(f, patterns) and not proto.vendored(f)
                    and p.stat().st_size <= MAX_BYTES):
                protos.append(proto.parse(p.read_text(encoding="utf-8", errors="replace"), f))
        py_deps = python_dependencies(root)
        not_scanned = unscanned.report(tree, set(results), lambda f: excluded(f, patterns + BUILD_EXCLUDES),
                                       lambda f: (root / f).read_text(encoding="utf-8", errors="replace"))
        pkg_deps = _package_deps(root, tree)
        gateway_routes = gateways.read(tree, lambda f: excluded(f, patterns + BUILD_EXCLUDES)
                                       or (root / f).stat().st_size > MAX_BYTES,
                                       lambda f: (root / f).read_text(encoding="utf-8", errors="replace"))
        mapper_sql, sql_files = sqlfiles.read(root, tree, lambda f: excluded(f, patterns + BUILD_EXCLUDES)
                                              or (root / f).stat().st_size > MAX_BYTES)

    names = _module_names(modules, results, file_mod, build_names)
    for f, r in results.items():
        _unalias(f, r, results, names)
    _resolve_handlers(results, file_mod, reg, names)
    _compose_includes(results)
    _compose_mounts(results, sources)
    _file_system_routes(pkg_deps, results, sources)
    for f, r in results.items():
        if f in lines:
            _file_node(r, f, file_mod[f], LANGS[Path(f).suffix][0], lines[f], reg)
            _file_level_handlers(r, reg)
    for r in results.values():
        for route in r["routes"]:
            route.pop("call_end", None)
    wrappers.find(results, sources, lambda f: _client_heads(st, results[f], LANGS[Path(f).suffix][0]), NEW_FILE_NODE)
    for f, r in results.items():   # a request descriptor outside any function
        if f in lines and any(c["in"] == NEW_FILE_NODE for c in r.get("clients", [])):
            _file_node(r, f, file_mod[f], LANGS[Path(f).suffix][0], lines[f], reg)
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
    _class_routes(results)   # after _implements: a class's verbs include its repo bases'
    _go_implements(nodes)
    names = _module_names(modules, results, file_mod, build_names)
    internal = _internal(results, file_mod, mod_by_id, names, protos, aliases, py_deps)
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
    go_names = {Path(f).parent.as_posix(): r["go_package"] for f, r in results.items() if r.get("go_package")}
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
        bound = _bound_names(r["imports"])
        if lang == "go":   # `import ".../userstore"` binds `store` when that folder's files say `package store`
            bound = sorted(set(bound) | {go_names[d] for imp in r["imports"] for d in go_names
                                         if imp["target"] == d or imp["target"].endswith("/" + d)})
        if bound:   # the names a file's imports bind, for calls through them
            file_facts[f]["bound"] = bound
        if r["mounts"]:   # likewise for mount entries
            file_facts[f]["mounts"] = r["mounts"]
        if implemented := _implemented(r, sinks):
            file_facts[f]["implemented"] = implemented
        if r["tables"]:   # the key appears only where a table pattern matched
            file_facts[f]["tables"] = r["tables"]
        if r.get("repositories"):   # and for the entity each repository interface serves
            file_facts[f]["repositories"] = r["repositories"]
        if queues := queue_use.handled(r.get("queues", []), r["imports"], internal.get(lang, set()), lang):
            file_facts[f]["queues"] = queues   # likewise for in-process queue creation sites
        if r.get("jobs"):   # and for job system sites
            file_facts[f]["jobs"] = r["jobs"]

    _grpc_call_sites(file_facts, file_mod, nodes, results, set(gen_files))
    sqlfiles.attach(mapper_sql, nodes, file_facts)
    sqlfiles.orm_access(file_facts, nodes, sql_files)
    file_node = {n["file"]: n["id"] for n in nodes if n["kind"] == "file"}
    first_node = {}
    for n in nodes:
        if n["kind"] in ("class", "method"):
            first_node.setdefault(n["file"], n["id"])
    return {
        "stack": stack.report(st, {f: {"lang": LANGS[Path(f).suffix][0], "imports": results[f]["imports"],
                                       "routes": file_facts[f]["routes"], "tables": file_facts[f].get("tables", []),
                                       "queues": file_facts[f].get("queues", []),
                                       "jobs": file_facts[f].get("jobs", []),
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
        **({"gateways": gateway_routes} if gateway_routes else {}),   # the key only when a config has one
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
        families: dict[tuple[str, str], int] = {}
        for u in unrec:
            if "family" in u:
                families[(u["lang"], u["family"])] = families.get((u["lang"], u["family"]), 0) + 1
        lines += [f"- {lang} `{family}` holds {n} of these lines: when they sort the same way, one entry for "
                  f"`{family}` covers them all" for (lang, family), n in sorted(families.items())]
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
                                    ("queues", "Queue patterns:", "queue", "queues"),
                                    ("jobs", "Job patterns:", "job site", "job sites")):
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


# a folder of release, build or developer scripts: what its files read from the environment is no runtime setting
SCRIPT_FOLDER = re.compile(r"(?i)^(?:release|releases|scripts?|build-?tools?|buildSrc)$")


def _tooling_file(f: str) -> bool:
    """A file in a test, CI, docs, dev, release or scripts folder (unscanned.tooling, SCRIPT_FOLDER), judged above
    any `src` folder."""
    folder = f.rsplit("/", 1)[0] if "/" in f else ""
    segs = folder.split("/")
    above = segs[:segs.index("src")] if "src" in segs else segs
    return unscanned.tooling(folder) or any(SCRIPT_FOLDER.match(seg) for seg in above)


def _unscanned_lines(rep: dict) -> list[str]:
    """The Not scanned section: source in languages without a reader, and the deployables made mostly of it."""
    langs, deps = rep.get("languages", []), rep.get("deployables", [])
    if not langs and not deps and not rep.get("infrastructure"):
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
    if infra := rep.get("infrastructure", []):
        lines.append("Images of a database, broker, search or monitoring server (a stock image extended, no source of "
                     "its own): the datastore or broker node it runs, never a service — "
                     + ", ".join(f"`{d['folder']}` ({', '.join(d['images'])})" for d in infra))
        lines.append("")
    if tools := rep.get("tooling", []):
        lines.append("Images of tests, CI, docs or developer tooling (their folder says so): no deployables, no "
                     "service needed — " + ", ".join(f"`{d['folder']}`" for d in tools))
        lines.append("")
    return lines


def _table_line(t: tuple, names: dict[str, str]) -> str:
    table, f, line, where, kind, *op = t
    name = names.get(where) or where
    return f"{table} ({f}:{line} {'defined on' if kind == 'defined' else 'in'} {name}{', ' + op[0] if op and op[0] else ''})"


def _route_shape(path: str) -> tuple[str, ...]:
    """A route's segments with every parameter alike, a `*` segment (any one segment) among them:
    `/api/cart/{id}/` -> ('api', 'cart', '{}')."""
    return tuple("{}" if x == "*" else re.sub(r"\{[^}]*\}", "{}", x) for x in path.split("/") if x)


def _reaches(client: tuple[str, ...], route: tuple[str, ...]) -> str | None:
    """`exact` when a client path is the route's, `suffix` when one ends with the other by two or more segments
    holding a word (a base or gateway prefix the other side adds or strips), else None."""
    if client == route:
        return "exact"
    short, long_ = sorted((client, route), key=len)
    if len(short) >= 2 and any(x != "{}" for x in short) and long_[-len(short):] == short:
        return "suffix"
    return None


def _likely_requests(s: dict) -> list[str]:
    """Each client call (`http clients`, `grpc clients`) with the repo routes or rpc servers it likely reaches:
    by method (ANY on either side fits) and path, or by proto key. Every match is listed, none chosen."""
    routes, servers = [], {}
    for f, ff in s["facts"].items():
        routes += [(r["method"], r["path"], _route_shape(r["path"]), r["handler"], f, r["line"]) for r in ff["routes"]]
        for g in ff.get("grpc", []):
            if g["side"] == "server":
                for k in g["keys"]:
                    servers.setdefault(k, []).append(f"{g['in']} ({f}:{g['line']})")
    out = []
    for f, ff in sorted(s["facts"].items()):
        for c in ff.get("clients", []):
            shape = _route_shape(c["path"])
            hits = [(how, m, p, h, rf, rl) for m, p, sh, h, rf, rl in routes
                    if (how := _reaches(shape, sh)) and (c["method"] == m or "ANY" in (c["method"], m))]
            if hits:
                to = "; ".join(f"`{m} {p}` → {h} ({rf}:{rl}){'' if how == 'exact' else ', by suffix'}"
                               for how, m, p, h, rf, rl in sorted(hits, key=lambda x: x[0] != "exact"))
                out.append(f"- {c['method']} {c['path']} ← {c['in']} ({f}:{c['line']}) → {to}")
        for g in ff.get("grpc", []):
            if g["side"] == "client":
                for k in g["keys"]:
                    if k in servers:
                        out.append(f"- {k} ← {g['in']} ({f}:{g['line']}) → {', '.join(servers[k])}")
    sends: dict[str, list[str]] = {}
    gets: dict[str, list[str]] = {}
    for f, ff in sorted(s["facts"].items()):
        for j in ff.get("jobs", []):
            if j["side"] == "publish":
                sends.setdefault(j["job"], []).append(f"{j['in']} ({f}:{j['line']})")
            elif j["side"] == "consume":
                gets.setdefault(j["job"], []).append(f"{j.get('node') or f} ({f}:{j['line']})")
    out += [f"- topic `{t}` ← {', '.join(sends[t])} → {', '.join(gets[t])}" for t in sorted(sends)
            if t in gets and not t.startswith("$")]   # `$topic`: a value the scan cannot read pairs nothing
    if not out:
        return []
    return [f"## Likely requests — {len(out)}", "",
            "A client call and the route or rpc server it likely reaches, by method and path (by suffix: one path "
            "ends with the other, a base or gateway prefix between them) or by proto key. Confirm each against the "
            "code and the address the caller is given, then write the `request` from the calling method to the "
            "handler, keyed by the route or rpc; a call that reaches none of them is an `ext-call`, or say in "
            "`problems` why it is none. A `topic` line pairs the messages sent to a broker topic or queue with the "
            "code receiving them, by name: an `event` through that topic's node from each sender, and one to each "
            "receiver:", *out, ""]


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
        lines += [f"## Tables defined in SQL, schema and migration files — {len(defined)}", "",
                  "`CREATE TABLE` in `.sql` files and the create-table calls of ORM schemas and migrations: tables that exist "
                  "whatever the code shows; "
                  "name them in the map where code reads or writes them:"]
        lines += [f"- {d['table']} ({d['file']}:{d['line']})" for d in defined] + [""]
    if gw := s.get("gateways"):
        lines += [f"## Gateway routes — {len(gw)}", "",
                  "Path prefixes a proxy or gateway config sends on (SKILL.md § Deployables, not folders): each is a "
                  "`request` from the gateway's service to the service the target names, citing the line; the "
                  "rewrite replaces the prefix on the way (none: the path goes on whole):"]
        lines += [f"- {g['prefix']} → {g['target']} ({g['file']}:{g['line']}, {g['kind']}"
                  + (f", rewrite {g['rewrite']})" if g.get("rewrite") else ")") for g in gw] + [""]
    lines += _likely_requests(s)
    names = {n["id"]: n["name"] for n in s["nodes"]}
    job_defs: dict[str, list[str]] = {}   # a job's name -> the nodes that define it, anywhere in the repo
    methods_named: dict[str, list[str]] = {}   # for a job that is a plain method (Hangfire `() => svc.Run()`)
    classes_named: dict[str, list[str]] = {}   # for a job that is a plain class (a Laravel command-bus job)
    for n in s["nodes"]:
        if n["kind"] == "method":
            methods_named.setdefault(n["name"], []).append(n["id"])
        elif n["kind"] == "class":
            classes_named.setdefault(n["name"], []).append(n["id"])
    for ff in s["facts"].values():
        for j in ff.get("jobs", []):
            if j["side"] == "define" and j.get("node"):
                job_defs.setdefault(j["job"], []).append(j["node"])
    for m in s["modules"]:
        files = [f for f, i in s["files"].items() if i["module"] == m["id"]]
        lines.append(f"## {m['id']} ({m['lang']}, {m['build']}, {len(files)} files)")
        routes_, clients, sinks, reads, writes, urls, envs = [], [], set(), set(), set(), set(), set()
        tool_envs: set[str] = set()
        implemented: list[str] = []
        tables, queues, jobs_def, jobs_enq, sent, received = [], [], [], [], [], []
        grpc_ends: dict[tuple[str, str], list[str]] = {}
        dags, wfs, refs, mounts = [], [], [], []
        for f in files:
            ff = s["facts"][f]
            routes_ += [f"{r['method']} {r['path']}" + (f" (after `{r['after']}`)" if r.get("after") else "")
                        + f" → {r['handler']} ({f}:{r['line']})" for r in ff["routes"]]
            mounts += [f"{x['path']}" + (f" (after `{x['after']}`)" if x.get("after") else "")
                       + (f" → {x['target']}" if x["target"] else "") + f" ({f}:{x['line']}"
                       + (f", composed onto {_plural(x['composed'], 'route', 'routes')})" if x.get("composed") else ")")
                       for x in ff.get("mounts", [])]
            tables += [(t["table"], f, t["line"], t["in"], t["kind"], t.get("op") or "") for t in ff.get("tables", [])]
            queues += [f"{q['delivery']} at {f}:{q['line']} in {names.get(q['in']) or q['in']}"
                       for q in ff.get("queues", [])]
            for j in ff.get("jobs", []):
                if j["side"] == "publish":
                    sent.append(f"{j['pattern']} `{j['job']}` ← {j['in']} ({f}:{j['line']})")
                elif j["side"] == "consume":
                    received.append(f"{j['pattern']} `{j['job']}` → {j.get('node') or 'the file'} ({f}:{j['line']})")
                elif j["side"] == "enqueue":
                    to, same = job_defs.get(j["job"], []), methods_named.get(j["job"], [])
                    kind = classes_named.get(j["job"], [])
                    where = f" → {', '.join(to)}" if to else \
                        f" → a class of that name: {', '.join(kind)}" if 0 < len(kind) <= 3 else \
                        f" → a method of that name: {', '.join(same)}" if 0 < len(same) <= 3 else \
                        f" → no definition; {len(same)} methods have that name" if same else " → no definition found"
                    jobs_enq.append(f"{j['pattern']} `{j['job']}` ← {j['in']} ({f}:{j['line']}){where}")
                else:
                    jobs_def.append(f"{j['pattern']} `{j['job']}`{' scheduled' if j['side'] == 'schedule' else ''}"
                                    f" → {j.get('node') or 'the file'} ({f}:{j['line']})")
            sinks |= {x["kind"] + ":" + x["lib"] for x in ff["sinks"]}
            for q in ff["sql"]:
                reads |= set(q["reads"])
                writes |= set(q["writes"])
            urls |= {u["url"] for u in ff["urls"]}
            (tool_envs if _tooling_file(f) else envs).update(e["key"] for e in ff["env_keys"])
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
            routes_ += [f"include_router({i['router']}, prefix={i['prefix']!r}) on {i['app']} ({f}:{i['line']}"
                        + (f", composed onto {_plural(i['composed'], 'route', 'routes')})" if i.get("composed")
                           else ", not composed: compose it yourself)")
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
                            ("in-process queues", queues), ("jobs defined", jobs_def), ("jobs enqueued", jobs_enq), ("messages published", sent), ("messages consumed", received),
                            ("url literals", sorted(urls)), ("env keys", sorted(envs)),
                            ("env keys of test, CI, dev and release files", sorted(tool_envs - envs))):
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
