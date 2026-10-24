"""What the scan leaves out because no reader exists for it: source files in languages the scanner does not read, and
the deployables (a folder with a Dockerfile, a compose service's build context) whose source is mostly such files.
Only source-like files count: images, lockfiles, docs and data are never listed."""
from __future__ import annotations

import posixpath
import re

import yaml

# file suffix -> language, for source the scanner has no reader for
# server templates and components: page routes and calls can live in them, but a web app holding many of them is
# still the scanned code's deployable, so they never make a deployable "mostly unscanned"
TEMPLATES = {"Razor": (".cshtml", ".razor"), "Twig": (".twig",), "ERB": (".erb",), "Handlebars": (".hbs",),
             "Liquid": (".liquid",), "Jinja": (".jinja", ".j2")}
SOURCE = {
    **dict.fromkeys((".c",), "C"), **dict.fromkeys((".h",), "C/C++ header"),
    **dict.fromkeys((".cc", ".cpp", ".cxx", ".c++", ".hpp", ".hh", ".hxx"), "C++"),
    **dict.fromkeys((".m", ".mm"), "Objective-C"), ".swift": "Swift", ".dart": "Dart",
    **dict.fromkeys((".ex", ".exs", ".heex"), "Elixir"), **dict.fromkeys((".erl", ".hrl"), "Erlang"),
    ".hs": "Haskell", **dict.fromkeys((".ml", ".mli"), "OCaml"), **dict.fromkeys((".fs", ".fsx"), "F#"),
    ".vb": "Visual Basic", **dict.fromkeys((".clj", ".cljs", ".cljc"), "Clojure"), ".groovy": "Groovy",
    **dict.fromkeys((".pl", ".pm"), "Perl"), ".lua": "Lua", ".r": "R", ".jl": "Julia", ".zig": "Zig",
    ".nim": "Nim", ".cr": "Crystal", ".elm": "Elm", ".sol": "Solidity", ".rake": "Rake",
    **{suf: lang for lang, sufs in TEMPLATES.items() for suf in sufs},
    **dict.fromkeys((".sh", ".bash", ".zsh"), "shell"), ".ps1": "PowerShell",
    **dict.fromkeys((".conf", ".vcl"), "server config"),
}
NAMES = {"Caddyfile": "server config", "Rakefile": "Rake"}
DOCKERFILE = re.compile(r"^(?:Dockerfile[^/]*|[^/]+\.[Dd]ockerfile)$")
# a folder segment that says the image is for tests, CI, docs, examples, benchmarks or a developer's tooling, not
# the product: a CI folder, `dev`, or a tooling word as a whole segment or a dashed part of one (`e2e-tests`,
# `docker-stack-docs`); never a word inside a product name (`payment-integration`)
TOOLING = re.compile(r"(?i)^(?:\.(?:github|gitlab|circleci|buildkite|devcontainer)|dev|devtools?|dev-tools?|ci|"
                     r"(?:.*[-_.])?(?:tests?|testing|e2e|docs|documentation|examples?|samples?|benchmarks?)"
                     r"(?:[-_.].*)?)$")


def tooling(folder: str) -> bool:
    """A folder of TOOLING, judged on the segments above any source tree (`src/main/java/dev/acme` is a package)."""
    segs = folder.split("/")
    above = segs[:segs.index("src")] if "src" in segs else segs
    return any(TOOLING.match(seg) for seg in above)


# source that runs beside any deployable (scripts, server config): it never makes one unscanned by its share
AUXILIARY = {"shell", "PowerShell", "server config", "Rake"}
MANY = 100   # this many unread source files, a fifth of the read ones or more, make a deployable unscanned in part
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


def compose_services(doc) -> dict:
    """The services of a parsed compose file: its `services` map, or for a version 1 file (no `services` key) each
    top-level entry that names an `image` or a `build`."""
    if not isinstance(doc, dict):
        return {}
    if "services" in doc:
        return doc["services"] if isinstance(doc["services"], dict) else {}
    return {k: v for k, v in doc.items() if isinstance(v, dict) and ("image" in v or "build" in v)}


def _build_contexts(path: str, text: str) -> list[tuple[str, str, str | None]]:
    """(compose service, its build context folder, the Dockerfile it names or None) for each service a compose file
    builds from this repo."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    out = []
    for name, svc in compose_services(doc).items():
        build = svc.get("build") if isinstance(svc, dict) else None
        context = build.get("context", ".") if isinstance(build, dict) else build
        if isinstance(context, str) and "://" not in context and not context.startswith("git@"):
            folder = posixpath.normpath(posixpath.join(_folder(path), context))
            named = build.get("dockerfile") if isinstance(build, dict) else None
            recipe = posixpath.normpath(posixpath.join(folder, named)) if isinstance(named, str) else None
            if not folder.startswith(".."):
                out.append((str(name), folder, recipe))
    return out


def report(files: list[str], scanned: set[str], skip, read) -> dict:
    """`files`: every file of the tree; `scanned`: the files the scan read; `skip(path)`: excluded (vendored, build
    output, tests, docs); `read(path)`: a file's text. Returns `languages` (each unscanned language with its file count
    and outermost folders) and `deployables` (each deployable folder whose source is mostly unscanned, holds MANY unscanned
    files or more, or has no scanned source at all) and `tooling` (the image folders of tests, CI, docs or developer
    tooling: no deployables)."""
    source = {f: lang for f in files if not skip(f) and (lang := language(f))}
    by_lang: dict[str, list[str]] = {}
    for f, lang in source.items():
        by_lang.setdefault(lang, []).append(f)
    languages = [{"lang": lang, "files": len(fs), "folders": _outermost({_folder(f) for f in fs})}
                 for lang, fs in sorted(by_lang.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    found: dict[str, dict] = {}
    recipes: set[str] = set()   # Dockerfiles a compose service builds with another folder as its context
    for f in files:
        name = f.rsplit("/", 1)[-1]
        if skip(f):
            continue
        if DOCKERFILE.match(name):
            found.setdefault(_folder(f), {"dockerfiles": [], "compose": []})["dockerfiles"].append(f)
        elif COMPOSE.match(name):
            for svc, folder, recipe in _build_contexts(f, read(f)):
                found.setdefault(folder, {"dockerfiles": [], "compose": []})["compose"].append([svc, f])
                if recipe is not None and _folder(recipe) != folder:
                    recipes.add(recipe)
    deployables, tools = [], []
    for folder, how in sorted(found.items()):
        if not how["compose"] and how["dockerfiles"] and set(how["dockerfiles"]) <= recipes:
            continue   # `docker/local.Dockerfile` of a service built from `.`: the context is the deployable
        if tooling(folder):
            tools.append({"folder": folder, **how})
            continue
        mine = sum(1 for f in scanned if _inside(f, folder))
        missed: dict[str, int] = {}
        for f, lang in source.items():
            if _inside(f, folder) and lang not in TEMPLATES:
                missed[lang] = missed.get(lang, 0) + 1
        main = sum(n for lang, n in missed.items() if lang not in AUXILIARY)
        if mine == 0 or sum(missed.values()) > mine or (main >= MANY and 5 * main >= mine):
            deployables.append({"folder": folder, **how, "scanned": mine,
                                "unscanned": [[lang, n] for lang, n in sorted(missed.items(), key=lambda kv: (-kv[1], kv[0]))]})
    return {"languages": languages, "deployables": deployables, **({"tooling": tools} if tools else {})}
