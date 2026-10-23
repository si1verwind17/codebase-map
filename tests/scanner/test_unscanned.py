"""What the scan leaves out: source in languages without a reader, and deployables made mostly of it."""
from vizcode import mapcheck, structure

COMPOSE = ("services:\n  shop:\n    build: ./shop\n  ui:\n    build:\n      context: ./ui\n"
           "  db:\n    image: postgres:16\n")
FILES = {
    "docker-compose.yml": COMPOSE,
    "shop/Dockerfile": "FROM python:3.12\nCMD [\"python\", \"app.py\"]\n",
    "shop/app.py": "def main():\n    pass\n",
    "proxy/Dockerfile": "FROM proxy\nCOPY proxy.conf /etc/proxy/proxy.conf\n",
    "proxy/proxy.conf": "server { listen 80; }\n",
    "rates/Dockerfile": "FROM gcc\n",
    "rates/src/main.cpp": "int main() { return 0; }\n",
    "rates/src/money.h": "int cents();\n",
    "rates/build.sh": "#!/bin/sh\nmake\n",
    "ui/lib/app.ex": "defmodule App do\nend\n",
    "ui/lib/page.ex": "defmodule Page do\nend\n",
    "ui/mix.exs": "defmodule Ui.MixProject do\nend\n",
    "ui/assets/app.js": "export function start() {}\n",
    "relay/Dockerfile": "FROM relay\nCOPY config.yaml /etc/config.yaml\n",
    "relay/config.yaml": "receivers: {}\n",
    "scripts/deploy.sh": "#!/bin/sh\necho deploy\n",
    "vendor/zlib/inflate.c": "int inflate();\n",
    "docs/logo.png": "png",
    "package-lock.json": "{}\n",
    "README.md": "# shop\n",
}


def test_unscanned_languages_and_deployables(make_repo):
    s = structure.build(make_repo(FILES), "docs/viz-code")
    langs = {x["lang"]: (x["files"], x["folders"]) for x in s["unscanned"]["languages"]}
    # vendored code, images, lockfiles and docs are never listed
    assert langs == {"Elixir": (3, ["ui"]), "shell": (2, ["rates", "scripts"]), "C++": (1, ["rates/src"]),
                     "C/C++ header": (1, ["rates/src"]), "server config": (1, ["proxy"])}
    got = {d["folder"]: d for d in s["unscanned"]["deployables"]}
    # shop is scanned Python: not listed; ui is mostly Elixir beside one scanned script
    assert sorted(got) == ["proxy", "rates", "relay", "ui"]
    assert got["ui"]["compose"] == [["ui", "docker-compose.yml"]] and got["ui"]["dockerfiles"] == []
    assert got["ui"]["scanned"] == 1 and got["ui"]["unscanned"] == [["Elixir", 3]]
    assert got["rates"]["dockerfiles"] == ["rates/Dockerfile"] and got["rates"]["scanned"] == 0
    assert got["relay"]["unscanned"] == []


def test_summary_says_what_was_not_scanned(make_repo):
    s = structure.build(make_repo(FILES), "docs/viz-code")
    md = structure.summary_md(s)
    assert "## Not scanned — 5 languages without a reader, 4 deployables mostly in them" in md
    assert "- Elixir — 3 files: ui\n" in md and "- shell — 2 files: rates, scripts\n" in md
    assert ("- deployable `ui` (compose service `ui` in docker-compose.yml) — 1 file scanned; "
            "not scanned: Elixir 3\n") in md
    assert "- deployable `relay` (Dockerfile `relay/Dockerfile`) — 0 files scanned; no source the scanner " \
           "reads\n" in md
    assert md.index("## Not scanned") < md.index("## mod:")


def test_nothing_unscanned_leaves_the_section_out(make_repo):
    s = structure.build(make_repo({"shop/app.py": "def main():\n    pass\n", "shop/Dockerfile": "FROM python\n"}))
    assert s["unscanned"] == {"languages": [], "deployables": []}
    assert "## Not scanned" not in structure.summary_md(s)


def test_deployable_unscanned_warning_until_a_service_or_problem_names_it(make_repo):
    md = structure.summary_md(structure.build(make_repo(FILES), "docs/viz-code"))
    cmap = {"nodes": [{"id": "ext:http:proxy", "kind": "external", "name": "proxy"},
                      {"id": "svc:rates", "kind": "service", "name": "currency",
                       "evidence": [{"file": "rates/Dockerfile", "line": 1}]},
                      {"id": "svc:ui", "kind": "service", "name": "ui",
                       "evidence": [{"file": "docker-compose.yml", "line": 4}]}],
            "relations": [], "problems": [{"text": "`relay` runs a vendor image with its config only"}]}
    got = [w for w in mapcheck.warnings(cmap, md) if w["id"] == "deployable.unscanned"]
    assert [w["detail"].split("`")[1] for w in got] == ["proxy"]
    assert "model it as a service" in got[0]["detail"]


def test_server_templates_are_listed_but_never_make_a_deployable_unscanned(make_repo):
    files = {"composer.json": "{}\n", "Dockerfile": "FROM php\n", "src/Kernel.php": "<?php\nclass Kernel {}\n",
             **{f"templates/page{i}.html.twig": "{{ x }}\n" for i in range(3)}, "Views/Home.cshtml": "@model X\n"}
    s = structure.build(make_repo(files), "docs/viz-code")
    langs = {x["lang"]: x["files"] for x in s["unscanned"]["languages"]}
    assert langs == {"Twig": 3, "Razor": 1}
    assert s["unscanned"]["deployables"] == []
