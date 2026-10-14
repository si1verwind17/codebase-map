"""Build-level modules: sbt projects, Python packages, loose script folders, build files of other languages
(packs/modules.yaml), else their top folders."""
from __future__ import annotations

import json
import posixpath
import re
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Callable

import yaml

from .adapters.langs import BY_SUFFIX, SPECS

SBT_PROJECT = re.compile(r'project\s*(?:in|\.in)\s*\(?\s*file\(\s*"([^"]+)"\s*\)')


def _read(path: Path) -> str:
    """A build file; a byte-order mark (Windows editors write one) is dropped."""
    return path.read_text(encoding="utf-8-sig", errors="replace")


def _maven_modules(path: Path) -> list[str]:
    """`<modules><module>api</module>...`; commented-out modules left out."""
    return re.findall(r"<module>\s*([^<]+?)\s*</module>", re.sub(r"<!--.*?-->", "", _read(path), flags=re.S))


def _gradle_include(path: Path) -> list[str]:
    """`include(":a", ":b:c")`, `include 'a', 'b'` (continued after a trailing comma) -> a, b/c."""
    src = re.sub(r"/\*.*?\*/", "", re.sub(r"(?m)^\s*//.*$", "", _read(path)), flags=re.S)
    out = []
    for m in re.finditer(r"\binclude\b\s*(?:\(([^)]*)\)|((?:[^\n]*,[ \t]*\n)*[^\n]*))", src):
        body = m.group(1) if m.group(1) is not None else m.group(2)
        out += [s.strip(":").replace(":", "/") for s in re.findall(r"[\"']([^\"']+)[\"']", body)]
    return out


def _npm_workspaces(path: Path) -> list[str]:
    """package.json `workspaces` (a list, or `{packages: [...]}`); pnpm-workspace.yaml `packages`."""
    try:
        doc = yaml.safe_load(_read(path)) if path.suffix == ".yaml" else json.loads(_read(path))
    except (ValueError, yaml.YAMLError):
        return []
    ws = doc.get("packages" if path.suffix == ".yaml" else "workspaces") if isinstance(doc, dict) else None
    if isinstance(ws, dict):
        ws = ws.get("packages")
    return [w for w in ws if isinstance(w, str)] if isinstance(ws, list) else []


def _cargo_members(path: Path) -> list[str]:
    """`[workspace] members = [...]`, less `exclude = [...]` (as `!` entries)."""
    try:
        ws = tomllib.loads(_read(path)).get("workspace")
    except tomllib.TOMLDecodeError:
        return []

    def names(key: str) -> list[str]:
        v = ws.get(key) if isinstance(ws, dict) else None
        return [m for m in v if isinstance(m, str)] if isinstance(v, list) else []
    return names("members") + ["!" + m for m in names("exclude")]


READERS: dict[str, Callable[[Path], list[str]]] = {
    "maven-modules": _maven_modules,
    "gradle-include": _gradle_include,
    "npm-workspaces": _npm_workspaces,
    "cargo-members": _cargo_members,
    "each-file": lambda path: [],
}


def _go_module(path: Path) -> str | None:
    """go.mod `module github.com/acme/shop`."""
    m = re.search(r'(?m)^\s*module\s+"?([^\s"]+)"?', re.sub(r"//[^\n]*", "", _read(path)))
    return m.group(1) if m else None


def _npm_name(path: Path) -> str | None:
    """package.json `name`."""
    try:
        doc = json.loads(_read(path))
    except ValueError:
        return None
    name = doc.get("name") if isinstance(doc, dict) else None
    return name if isinstance(name, str) and name else None


def _cargo_name(path: Path) -> str | None:
    """Cargo.toml `[package] name`, as code writes it (`shop-core` -> `shop_core`)."""
    try:
        pkg = tomllib.loads(_read(path)).get("package")
    except tomllib.TOMLDecodeError:
        return None
    name = pkg.get("name") if isinstance(pkg, dict) else None
    return name.replace("-", "_") if isinstance(name, str) and name else None


NAME_READERS: dict[str, Callable[[Path], str | None]] = {
    "go-module": _go_module,
    "npm-name": _npm_name,
    "cargo-package": _cargo_name,
}


@dataclass(frozen=True)
class Ecosystem:
    files: tuple[str, ...]
    langs: tuple[str, ...]
    build: str
    members: str
    name: str | None = None


def _load() -> tuple[Ecosystem, ...]:
    doc = yaml.safe_load((Path(__file__).parent / "packs" / "modules.yaml").read_text(encoding="utf-8"))
    out = []
    for name, e in doc.items():
        eco = Ecosystem(tuple(e["files"]), tuple(e["langs"]), e["build"], e["members"], e.get("name"))
        if eco.members not in READERS or not set(eco.langs) <= set(SPECS) \
                or (eco.name is not None and eco.name not in NAME_READERS):
            raise ValueError(f"packs/modules.yaml: {name}: unknown reader or language")
        out.append(eco)
    return tuple(out)


ECOSYSTEMS = _load()
BUILD_FILES = tuple(dict.fromkeys(f for e in ECOSYSTEMS for f in e.files))


def _norm(p: str) -> str:
    p = p.strip().strip("/")
    return "." if p in ("", ".") else p


def _under(path: str, mod_path: str) -> bool:
    return mod_path == "." or path == mod_path or path.startswith(mod_path + "/")


def _module(path: str, lang: str, build: str) -> dict:
    return {"id": f"mod:{path}", "path": path, "lang": lang, "build": build}


def _folders(f: str) -> list[str]:
    """The folders above a file, nearest first, ending with "."."""
    return [str(d) for d in PurePosixPath(f).parents]


def _glob(folder: str, pattern: str) -> bool:
    """A folder path against a member glob, one segment at a time (`*` stays in its folder, `**` spans any)."""
    def match(fs: list[str], ps: list[str]) -> bool:
        if not ps:
            return not fs
        if ps[0] == "**":
            return any(match(fs[i:], ps[1:]) for i in range(len(fs) + 1))
        return bool(fs) and fnmatchcase(fs[0], ps[0]) and match(fs[1:], ps[1:])
    return match(folder.split("/"), pattern.split("/"))


def _members(base: str, entries: list[str], folders: set[str]) -> set[str]:
    """Member folders a build file in `base` lists; globs expand against `folders`, `!` entries are taken out."""
    def resolve(entry: str) -> str | None:
        p = posixpath.normpath(posixpath.join(base, entry.strip().rstrip("/")))
        return None if p == ".." or p.startswith("../") else p
    found: set[str] = set()
    for sign in ("", "!"):
        for e in entries:
            if e.startswith("!") != bool(sign) or (p := resolve(e.removeprefix("!"))) is None:
                continue
            hit = {d for d in folders if _glob(d, p)} if any(c in p for c in "*?[") else {p}
            found = found - hit if sign else found | hit
    return found


def _build_roots(root: Path, files: list[str]) -> dict[str, dict[str, str]]:
    """lang -> {folder: build}: the folders above the language's files that hold a build file of its ecosystem,
    and the members such files list. The first ecosystem in packs/modules.yaml wins a folder."""
    folders = {d for f in files if PurePosixPath(f).suffix in BY_SUFFIX for d in _folders(f)}
    out: dict[str, dict[str, str]] = {}
    for eco in ECOSYSTEMS:
        found: dict[str, str] = {}
        for d in sorted(folders):
            for name in eco.files:
                for bf in sorted((root / d).glob(name)):
                    if bf.is_file():
                        found.setdefault(d, eco.build)
                        for m in sorted(_members(d, READERS[eco.members](bf), folders)):
                            found.setdefault(m, eco.build)
        for lang in eco.langs:
            for d, build in found.items():
                out.setdefault(lang, {}).setdefault(d, build)
    return out


def detect_modules(root: Path, files: list[str]) -> tuple[list[dict], dict[str, str], list[str]]:
    """Return (modules, file -> module id, unassigned files)."""
    modules: dict[str, dict] = {}
    file_mod: dict[str, str] = {}
    unassigned: list[str] = []

    sbt = root / "build.sbt"
    sbt_paths = [_norm(m) for m in SBT_PROJECT.findall(_read(sbt))] if sbt.exists() else []
    for p in sbt_paths:
        modules[f"mod:{p}"] = _module(p, "scala", "sbt")

    for f in files:
        if f.endswith(".scala"):
            if sbt_paths:
                owners = [p for p in sbt_paths if _under(f, p)]
                if not owners:
                    unassigned.append(f)
                    continue
                file_mod[f] = f"mod:{max(owners, key=len)}"
            else:
                top = f.split("/")[0] if "/" in f else "."
                modules.setdefault(f"mod:{top}", _module(top, "scala", "dir"))
                file_mod[f] = f"mod:{top}"
        elif f.endswith(".py"):
            d = PurePosixPath(f).parent
            if (root / d / "__init__.py").exists() and str(d) != ".":
                top = d
                while str(top.parent) != "." and (root / top.parent / "__init__.py").exists():
                    top = top.parent
                path, build = str(top), "python-package"
            else:
                path, build = _norm(str(d)), "python-scripts"
            mid = f"mod:{path}"
            if mid in modules and modules[mid]["lang"] != "python":
                mid = f"mod:{path}#py"
            modules.setdefault(mid, {**_module(path, "python", build), "id": mid})
            file_mod[f] = mid

    # languages of adapters/langs.py: the nearest build file of the language's ecosystem, else the top folder;
    # one module per language, so in a folder shared with another language the later one in sorted order
    # (Python and Scala always come first, keeping their ids) gets `mod:<path>#<lang>`
    roots = _build_roots(root, files)
    generic = [(BY_SUFFIX[PurePosixPath(f).suffix].lang, f) for f in files if PurePosixPath(f).suffix in BY_SUFFIX]
    for lang, f in sorted(generic):
        owners = roots.get(lang, {})
        path = next((d for d in _folders(f) if d in owners), None)
        build = owners[path] if path is not None else "dir"
        if path is None:
            path = f.split("/")[0] if "/" in f else "."
        mid = f"mod:{path}"
        if mid in modules and modules[mid]["lang"] != lang:
            mid = f"mod:{path}#{lang}"
        modules.setdefault(mid, {**_module(path, lang, build), "id": mid})
        file_mod[f] = mid

    # Filter out modules with no source files assigned
    modules_with_files = set(file_mod.values())
    filtered_modules = {mid: m for mid, m in modules.items() if mid in modules_with_files}

    return sorted(filtered_modules.values(), key=lambda m: m["id"]), file_mod, unassigned


def names_from_build_files(root: Path, modules: list[dict]) -> dict[str, str]:
    """module id -> the name other code imports it by (go.mod `module`, package.json `name`, Cargo `[package]
    name`), read from the module folder's build file by its ecosystem's `name` reader."""
    out: dict[str, str] = {}
    for m in modules:
        eco = next((e for e in ECOSYSTEMS if e.build == m["build"] and m["lang"] in e.langs), None)
        if eco is None or eco.name is None:
            continue
        for bf in (root / m["path"] / f for f in eco.files):
            if bf.is_file() and (name := NAME_READERS[eco.name](bf)):
                out[m["id"]] = name
                break
    return out


def _jsonc(text: str):
    """JSON with comments and trailing commas (tsconfig.json); strings are kept whole."""
    text = re.sub(r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/', lambda m: m.group(1) or "", text, flags=re.S)
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


def path_aliases(root: Path, modules: list[dict]) -> set[str]:
    """Import prefixes tsconfig.json / jsconfig.json `compilerOptions.paths` maps into the repo (`@/*` -> `@`)."""
    out: set[str] = set()
    for m in modules:
        if m["lang"] not in ("typescript", "javascript"):
            continue
        for name in ("tsconfig.json", "jsconfig.json"):
            p = root / m["path"] / name
            try:
                doc = _jsonc(_read(p)) if p.is_file() else None
            except ValueError:
                doc = None
            opts = doc.get("compilerOptions") if isinstance(doc, dict) else None
            paths = opts.get("paths") if isinstance(opts, dict) else None
            if isinstance(paths, dict):
                out.update(k.removesuffix("*").rstrip("/") for k in paths if isinstance(k, str))
    out.discard("")
    return out
