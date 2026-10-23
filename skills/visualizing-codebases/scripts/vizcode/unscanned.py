"""What the scan leaves out because no reader exists for it: source files in languages the scanner does not read, and
the deployables (a folder with a Dockerfile, a compose service's build context) whose source is mostly such files.
Only source-like files count: images, lockfiles, docs and data are never listed."""
from __future__ import annotations

import posixpath
import re

import yaml

# file suffix -> language, for source the scanner has no reader for
SOURCE = {
    **dict.fromkeys((".c",), "C"), **dict.fromkeys((".h",), "C/C++ header"),
    **dict.fromkeys((".cc", ".cpp", ".cxx", ".c++", ".hpp", ".hh", ".hxx"), "C++"),
    **dict.fromkeys((".m", ".mm"), "Objective-C"), ".swift": "Swift", ".dart": "Dart",
    **dict.fromkeys((".ex", ".exs", ".heex"), "Elixir"), **dict.fromkeys((".erl", ".hrl"), "Erlang"),
    ".hs": "Haskell", **dict.fromkeys((".ml", ".mli"), "OCaml"), **dict.fromkeys((".fs", ".fsx"), "F#"),
    ".vb": "Visual Basic", **dict.fromkeys((".clj", ".cljs", ".cljc"), "Clojure"), ".groovy": "Groovy",
    **dict.fromkeys((".pl", ".pm"), "Perl"), ".lua": "Lua", ".r": "R", ".jl": "Julia", ".zig": "Zig",
    ".nim": "Nim", ".cr": "Crystal", ".elm": "Elm", ".sol": "Solidity",
    **dict.fromkeys((".sh", ".bash", ".zsh"), "shell"), ".ps1": "PowerShell",
    **dict.fromkeys((".conf", ".vcl"), "server config"),
}
NAMES = {"Caddyfile": "server config"}
DOCKERFILE = re.compile(r"^(?:Dockerfile[^/]*|[^/]+\.[Dd]ockerfile)$")
COMPOSE = re.compile(r"^(?:docker-)?compose[^/]*\.ya?ml$")


def language(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    return NAMES.get(name) or SOURCE.get(posixpath.splitext(name)[1].lower())


def _folder(path: str) -> str:
    return posixpath.dirname(path) or "."


def _inside(path: str, folder: str) -> bool:
    return folder == "." or path.startswith(folder + "/")


def _outermost(folders: set[str]) -> list[str]:
    """The folders no other listed folder holds."""
    return sorted(f for f in folders if not any(o != f and _inside(f, o) for o in folders))


def _build_contexts(path: str, text: str) -> list[tuple[str, str]]:
    """(compose service, its build context folder) for each service a compose file builds from this repo."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    services = doc.get("services") if isinstance(doc, dict) else None
    out = []
    for name, svc in (services if isinstance(services, dict) else {}).items():
        build = svc.get("build") if isinstance(svc, dict) else None
        context = build.get("context", ".") if isinstance(build, dict) else build
        if isinstance(context, str) and "://" not in context and not context.startswith("git@"):
            folder = posixpath.normpath(posixpath.join(_folder(path), context))
            if not folder.startswith(".."):
                out.append((str(name), folder))
    return out


def report(files: list[str], scanned: set[str], skip, read) -> dict:
    """`files`: every file of the tree; `scanned`: the files the scan read; `skip(path)`: excluded (vendored, build
    output, tests, docs); `read(path)`: a file's text. Returns `languages` (each unscanned language with its file count
    and outermost folders) and `deployables` (each deployable folder whose source is mostly unscanned, or that has no
    scanned source at all)."""
    source = {f: lang for f in files if not skip(f) and (lang := language(f))}
    by_lang: dict[str, list[str]] = {}
    for f, lang in source.items():
        by_lang.setdefault(lang, []).append(f)
    languages = [{"lang": lang, "files": len(fs), "folders": _outermost({_folder(f) for f in fs})}
                 for lang, fs in sorted(by_lang.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    found: dict[str, dict] = {}
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if skip(f):
            continue
        if DOCKERFILE.match(name):
            found.setdefault(_folder(f), {"dockerfiles": [], "compose": []})["dockerfiles"].append(f)
        elif COMPOSE.match(name):
            for svc, folder in _build_contexts(f, read(f)):
                found.setdefault(folder, {"dockerfiles": [], "compose": []})["compose"].append([svc, f])
    deployables = []
    for folder, how in sorted(found.items()):
        mine = sum(1 for f in scanned if _inside(f, folder))
        missed: dict[str, int] = {}
        for f, lang in source.items():
            if _inside(f, folder):
                missed[lang] = missed.get(lang, 0) + 1
        if mine == 0 or sum(missed.values()) > mine:
            deployables.append({"folder": folder, **how, "scanned": mine,
                                "unscanned": [[lang, n] for lang, n in sorted(missed.items(), key=lambda kv: (-kv[1], kv[0]))]})
    return {"languages": languages, "deployables": deployables}
