"""Type links (spec: traces §1.2): each type in a method signature resolved to repo class ids.

`signature.params[i].refs` and `signature.returns_refs` list the class ids a type text names, in the order the
names first appear; the key is left out when nothing resolves. Every name in the type text is tried
(`List[Reservation]`, `Future<Charge>`, `Map[BayId, Status]`); string literals are not, except Python forward
references. A qualified name (`http.Request`, `crate::models::Charge`) resolves only when it is a class's qualified
name, or its first part is an import naming the class's package. A bare name resolves by, in order: a class in
the same file; an import; the same package; a class name unique in the language family. A level with one match
resolves it; a level with several leaves it unresolved; a level with none passes to the next. A name the file
declares as a non-class type, or imports explicitly from outside the repo, stops at its level unresolved. A declared
type parameter (`<TEvent>`, the adapters' `type_params`) never resolves; nor does a qualified name whose first part
is a library import (`log.Logger` with the repo's own `internal/log`)."""
from __future__ import annotations

import posixpath
import re
import sys
from typing import Callable

from . import stack
from .adapters.langs import SPECS

IDENT = re.compile(r"[A-Za-z_]\w*")
QUALIFIED = re.compile(r"((?:[A-Za-z_]\w*(?:\.|::|\\))*)([A-Za-z_]\w*)")
DOUBLE_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"')
JS_QUOTED = re.compile(r"""'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`""")
PY_QUOTED = re.compile(r"""(["'])(.*?)\1""")
PY_LITERAL = re.compile(r"\bLiteral\[")
SEPARATORS = re.compile(r"::|[/\\]")
RELATIVE_HEAD = re.compile(r"^(?:\.+|(?:crate|self|super)\.)+")


TYPE_PARAM = re.compile(r"^[A-Z]$")      # almost always a type parameter, declared or not (a class's own `[A]`)


def python_relative(f: str, imp: dict, files) -> set[str]:
    """The scanned files a Python relative import (`.models`, `..pkg.models`, `.` + names) names, anchored on
    the importing file's folder."""
    target = imp["target"]
    dots = len(target) - len(target.lstrip("."))
    base = posixpath.dirname(f)
    for _ in range(dots - 1):
        base = posixpath.dirname(base)
    rest = target[dots:].replace(".", "/")
    mods = [posixpath.join(base, rest)] if rest else [posixpath.join(base, n) for n in imp.get("names") or []]
    cands = [c for m in mods for c in (m + ".py", m + "/__init__.py")]
    if not rest:
        cands.append(posixpath.join(base, "__init__.py"))
    return {posixpath.normpath(c) for c in cands} & set(files)


def type_names(type_text: str | None) -> list[str]:
    """The identifiers of a type text, each once, in order of first appearance."""
    return list(dict.fromkeys(IDENT.findall(type_text or "")))


def without_strings(type_text: str, lang: str) -> str:
    """A type text with its string literals left out (TS `'a' | 'b'`, Python `Literal["x"]`); a quoted Python type
    (`"Date"`, `List["Date"]`) is a forward reference and loses only its quotes."""
    if lang == "python":
        out, i = [], 0
        for m in PY_LITERAL.finditer(type_text):
            if m.start() < i:
                continue
            depth, j = 1, m.end()
            while j < len(type_text) and depth:
                depth += {"[": 1, "]": -1}.get(type_text[j], 0)
                j += 1
            out.append(type_text[i:m.end()] + "]")
            i = j
        return PY_QUOTED.sub(r"\2", "".join(out) + type_text[i:])
    text = DOUBLE_QUOTED.sub("", type_text)
    return JS_QUOTED.sub("", text) if lang in ("typescript", "javascript") else text


def qualified_names(type_text: str | None, lang: str = "") -> list[tuple[str, str]]:
    """(dotted prefix, name) of each name in a type text, each once, in order of first appearance:
    `Map[str, models.Quote]` -> ("", Map), ("", str), ("models", Quote); prefix parts are no names themselves."""
    text = without_strings(type_text or "", lang)
    return list(dict.fromkeys((dotted(m.group(1)), m.group(2)) for m in QUALIFIED.finditer(text)))


def dotted(path: str) -> str:
    """`crate::models::Charge`, `App\\Models\\Charge`, `../models/charge` -> dotted, with a leading `.`/`..`,
    `crate::`, `self::` or `super::` dropped."""
    return RELATIVE_HEAD.sub("", SEPARATORS.sub(".", path)).strip(".")


def qualified(cid: str) -> str:
    """A class id's qualified name, dotted: `svc::internal/orders.Repo` -> `internal.orders.Repo`."""
    return dotted(cid.split("::", 1)[1] if "::" in cid else cid)


def names_import(qname: str, name: str, path: str, short: bool = True) -> bool:
    """Does an import path (dotted) name the class `qname` called `name`: explicitly (`a.b.C`), or as its
    package or module (`a.b.*`, `using A.B`, `from a import b`, a Go import path ending in the class's folder)?
    `short`: may the path be only the end of the class's package (`shop.models` for `src.shop.models`)? Only
    for an import that names the repo's own code: a library `log` never names the repo's `internal/log`."""
    if path.rsplit(".", 1)[-1] == name and (qname == path or (short and qname.endswith("." + path))):
        return True
    owner = qname[: -len(name) - 1] if qname.endswith("." + name) else ""
    return bool(owner) and (path == owner or path.endswith("." + owner) or (short and owner.endswith("." + path)))


def link(nodes: list[dict], results: dict[str, dict], file_mod: dict[str, str],
         relative_file: Callable[[str, str], str | None], family: Callable[[str], str],
         internal_names: dict[str, set[str]] | None = None) -> None:
    """Set `refs` on each parameter and `returns_refs` on each method signature whose type names repo classes.
    `results`: the per-file parse results (`imports` with `names`, `renames`, `as`; `package`, `aliases`);
    `relative_file(file, target)`: the scanned file a relative import names, or None; `family(lang)`: the languages
    whose classes name each other's; `internal_names`: language -> import prefixes naming the repo's own code
    (packages, module names, tsconfig path aliases, workspace packages)."""
    by_name: dict[tuple[str, str], list[dict]] = {}
    for c in nodes:
        if c["kind"] == "class" and not c["id"].endswith("$") and not c["name"].startswith("new "):
            by_name.setdefault((family(c.get("lang") or ""), c["name"]), []).append(c)
    qnames = {c["id"]: qualified(c["id"]) for cs in by_name.values() for c in cs}
    # every run of segments of a class's package, and every package: does an import path name repo code?
    owners = {q.rsplit(".", 1)[0] for q in qnames.values() if "." in q}
    runs = {".".join(parts[i:j]) for o in owners for parts in [o.split(".")]
            for i in range(len(parts)) for j in range(i + 1, len(parts) + 1)}
    aliases: dict[str, set[str]] = {}
    for f, r in results.items():
        for a in r.get("aliases") or ():
            aliases.setdefault(a, set()).add(f)

    indexes: dict[str, tuple] = {}

    def internal(path: str, target: str, lang: str) -> bool:
        """Does an import (dotted `path`, raw `target`) name the repo's own code?"""
        parts = path.split(".")
        if path and (path in runs or any(".".join(parts[i:]) in owners for i in range(1, len(parts)))):
            return True
        if lang not in indexes:
            indexes[lang] = stack._index((internal_names or {}).get(lang, set()), stack.sep(lang))
        return bool(target) and stack._is_internal(target, indexes[lang], stack.sep(lang))

    repo_paths: set[tuple[str, str]] = set()   # (language, dotted import path) of imports naming repo code
    # the top-level Python packages and modules the repo's classes live in (`email` for email/sender.py)
    py_heads = {qnames[c["id"]].split(".", 1)[0] for (fam, _), cs in by_name.items() if fam == "python" for c in cs}

    def stdlib(imp: dict, lang: str) -> bool:
        """`import logging` is the standard library's, whatever the repo's files are called, unless the repo has a
        top-level package or module of that name (an `email/` package of its own)."""
        head = imp["target"].split(".")[0]
        return (lang == "python" and not imp.get("relative") and head in sys.stdlib_module_names
                and head not in py_heads)

    def exact(path: str, imp: dict, lang: str) -> str:
        """Note whether an import path names the repo's own code by the language's own rules (a relative
        import, a declared package or module name), not merely by sharing a folder name; return the path."""
        if path and not stdlib(imp, lang) and (imp.get("relative") or internal("", imp["target"], lang)):
            repo_paths.add((lang, path))
        return path

    def module_of(f: str) -> tuple[str, str]:
        """(dotted file path without suffix, dotted folder) of a file."""
        stem = f.rsplit(".", 1)[0] if "." in posixpath.basename(f) else f
        return dotted(stem), dotted(posixpath.dirname(f))

    def under(path: str, f: str) -> bool:
        """Does a dotted import path name the file `f` (its module or its folder)?"""
        return any(m and (m == path or m.endswith("." + path) or path.endswith("." + m)) for m in module_of(f))

    def package(f: str | None) -> tuple | None:
        return (file_mod.get(f), results[f]["package"]) if f in results else None

    seen_imports: dict[str, tuple] = {}

    def imports(f: str, lang: str) -> tuple:
        """(dotted import paths, files named by relative imports, {first part of a qualified name: [(dotted path
        or None, files)]}, {explicitly imported name: [(dotted path or None, files, names repo code)]}) of a file."""
        if f not in seen_imports:
            extend = SPECS[lang].names_extend if lang in SPECS else True
            paths, files, heads, explicit = [], set(), {}, {}
            for imp in (results.get(f) or {}).get("imports", []):
                target, names, local = imp["target"], imp.get("names") or [], imp.get("as")
                renames = imp.get("renames") or {}
                plain = [n for n in names if n not in renames.values()]
                hit: set[str] = set()
                if imp.get("relative") and f.endswith(".py"):
                    hit = python_relative(f, imp, results)
                elif imp.get("relative") and (one := relative_file(f, target)) is not None:
                    hit = {one}
                if hit:
                    files |= hit
                    for n in names or [local or dotted(target).rsplit(".", 1)[-1]]:
                        heads.setdefault(n, []).append((None, hit))
                    for n in names:
                        explicit.setdefault(n, []).append((None, hit, True))
                elif names:
                    base = dotted(target)
                    inside = bool(imp.get("relative")) or (internal(base, target, lang) and not stdlib(imp, lang))
                    for n, member in [(n, n) for n in plain] + list(renames.items()):
                        if extend:
                            paths.append(exact(dotted(f"{target}.{member}"), imp, lang))
                            heads.setdefault(n, []).append((paths[-1], set()))
                        explicit.setdefault(n, []).append((base, set(), inside))
                elif p := exact(dotted(target), imp, lang):
                    paths.append(p)
                    owner, _, last = p.rpartition(".")
                    heads.setdefault(local or last, []).append((p, set()))
                    explicit.setdefault(last, []).append((owner, set(), internal(owner, target, lang)
                                                          and not stdlib(imp, lang)))
            seen_imports[f] = ([p for p in paths if p], files, heads, explicit)
        return seen_imports[f]

    def one(hit: list[dict]) -> str | None:
        ids_ = list(dict.fromkeys(c["id"] for c in hit))
        return ids_[0] if len(ids_) == 1 else None

    def resolve_qualified(prefix: str, name: str, cands: list[dict], f: str, lang: str) -> str | None:
        """`prefix.name`: a class in the package or file an import names by the prefix's first part, else a class
        whose qualified name it is; never a class found by the bare name alone, nor when the first part is an
        import of a library."""
        first, _, rest = prefix.partition(".")
        hit, heads = [], imports(f, lang)[2].get(first, [])
        if heads and not any(files or (lang, path) in repo_paths for path, files in heads):
            return None                   # the prefix is a library the file imports (`log.Logger`, `logging.X`)
        for path, files in heads:
            if files:
                hit += [c for c in cands if c.get("file") in files]
            elif path:
                hit += [c for c in cands if names_import(qnames[c["id"]], name, f"{path}.{rest}" if rest else path,
                                                         (lang, path) in repo_paths)]
        if not hit:
            full = f"{prefix}.{name}"
            hit = [c for c in cands if qnames[c["id"]] == full or qnames[c["id"]].endswith("." + full)]
        return one(hit)

    def resolve(prefix: str, name: str, f: str, lang: str, params: frozenset = frozenset()) -> str | None:
        cands = by_name.get((family(lang), name), [])
        if not cands or TYPE_PARAM.match(name) or (not prefix and name in params):
            return None
        if prefix:
            return resolve_qualified(prefix, name, cands, f, lang)
        if f in aliases.get(name, ()):
            return None                   # the file declares the name as a type that is no class
        paths, files, _, explicit = imports(f, lang)
        for i, level in enumerate((
                lambda c: c.get("file") == f,
                lambda c: c.get("file") in files or any(names_import(qnames[c["id"]], name, p, (lang, p) in repo_paths)
                                                        for p in paths),
                lambda c: package(f) is not None and package(c.get("file")) == package(f),
                lambda c: True)):
            hit = [c for c in cands if level(c)]
            if hit:
                return hit[0]["id"] if len(hit) == 1 else None
            if i == 1 and name in explicit:
                # imported by name, yet no class of the import: from outside the repo, or an alias there
                for path, named, inside in explicit[name]:
                    if not inside:
                        return None
                    if any(g in named or (path and under(path, g)) for g in aliases.get(name, ())):
                        return None
        return None

    for n in nodes:
        sig = n.get("signature") if n["kind"] == "method" else None
        if not sig:
            continue
        f, lang = n.get("file") or "", n.get("lang") or ""
        params = frozenset((results.get(f) or {}).get("type_params", {}).get(n["id"], ()))

        def refs(type_text: str | None) -> list[str]:
            return list(dict.fromkeys(r for q, t in qualified_names(type_text, lang)
                                      if (r := resolve(q, t, f, lang, params)) is not None))

        for p in sig["params"]:
            if found := refs(p.get("type")):
                p["refs"] = found
        if found := refs(sig.get("returns")):
            sig["returns_refs"] = found
