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


def test_tooling_images_apart_and_a_large_unread_share_counts(make_repo):
    """An image under a test, CI, docs or dev folder is no deployable; a deployable holding many unread source files
    (a fifth of the read ones or more) is listed even when read files outnumber them; shell scripts do not count
    to that share."""
    files = {"Dockerfile": "FROM clojure\n", "package.json": '{"name": "ui"}\n',
             **{f"frontend/src/c{i}.ts": "export const x = 1\n" for i in range(300)},
             **{f"src/backend/n{i}.clj": "(ns a)\n" for i in range(120)},
             "dev/sandbox/Dockerfile": "FROM node\n", "docker-stack-docs/Dockerfile": "FROM nginx\n",
             "e2e-tests/Dockerfile": "FROM node\n",
             "tools/Dockerfile": "FROM alpine\n", **{f"tools/s{i}.sh": "echo\n" for i in range(120)},
             **{f"tools/x{i}.ts": "export const y = 2\n" for i in range(200)}}
    s = structure.build(make_repo(files))
    assert [d["folder"] for d in s["unscanned"]["deployables"]] == ["."]
    assert [d["folder"] for d in s["unscanned"]["tooling"]] == ["dev/sandbox", "docker-stack-docs", "e2e-tests"]
    assert "no service needed — `dev/sandbox`, `docker-stack-docs`, `e2e-tests`" in structure.summary_md(s)


def test_env_keys_of_release_and_ci_scripts_have_a_line_of_their_own(make_repo):
    """A key only release, CI or test files read is no runtime setting: it is listed apart, and ext.missing,
    which reads the `env keys` line, never asks for it."""
    from vizcode import mapcheck
    files = {"package.json": '{"name": "app"}\n',
             "src/api.ts": "export const base = process.env.BILLING_URL\n",
             "release/src/slack.ts": "export const hook = process.env.SLACK_WEBHOOK_URL\n",
             "dev/notify.ts": "export const t = process.env.GITHUB_API_URL\n"}
    md = structure.summary_md(structure.build(make_repo(files)))
    assert "- **env keys:** BILLING_URL\n" in md
    assert "- **env keys of test, CI, dev and release files:** GITHUB_API_URL; SLACK_WEBHOOK_URL\n" in md
    missing = [w["detail"] for w in mapcheck.warnings({"nodes": [], "relations": []}, md) if w["id"] == "ext.missing"]
    assert len(missing) == 1 and "BILLING_URL" in missing[0]


def test_product_folders_and_jvm_packages_are_no_tooling(make_repo):
    files = {"pom.xml": "<project/>\n",
             "src/main/java/dev/acme/pay/Config.java": "package dev.acme.pay;\n\npublic class Config {\n"
                                                      "    String u = System.getenv(\"PAYMENT_GATEWAY_URL\");\n}\n",
             "bot/__init__.py": "", "bot/tools/__init__.py": "",
             "bot/tools/search.py": "import os\n\nURL = os.environ['SEARCH_API_URL']\n",
             "payment-integration/Dockerfile": "FROM node\n", "code-sandbox/Dockerfile": "FROM node\n",
             **{f"payment-integration/x{i}.ex": "x\n" for i in range(3)}, **{f"code-sandbox/y{i}.ex": "y\n" for i in range(3)}}
    s = structure.build(make_repo(files))
    md = structure.summary_md(s)
    assert "env keys of test" not in md and "PAYMENT_GATEWAY_URL" in md and "SEARCH_API_URL" in md
    assert not s["unscanned"].get("tooling")
    assert {d["folder"] for d in s["unscanned"]["deployables"]} == {"payment-integration", "code-sandbox"}


def test_rake_tasks_are_listed_but_never_make_a_deployable_unscanned(make_repo):
    files = {"Gemfile": "gem 'rails'\n", "Dockerfile": "FROM ruby\n", **{f"app/models/m{i}.rb": f"class M{i}; end\n" for i in range(5)},
             "Rakefile": "require_relative 'config/application'\n",
             **{f"lib/tasks/t{i}.rake": "task :x do\nend\n" for i in range(3)}}
    s = structure.build(make_repo(files), "docs/viz-code")
    assert {x["lang"]: x["files"] for x in s["unscanned"]["languages"]} == {"Rake": 4}
    assert s["unscanned"]["deployables"] == []
