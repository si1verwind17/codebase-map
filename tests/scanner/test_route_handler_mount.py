"""Regex routes: the optional `handler` group (resolved by name) and `mount: true` entries."""
import pytest
from conftest import with_stack

from vizcode import stack, structure

from helpers import write

EXPRESS = ("javascript:\n  routes:\n"
           "    - name: express\n      when: express\n      path: literal\n"
           "      regex: '\\b(?:app|router)\\.(?P<method>get|post)\\(\\s*[\"''](?P<path>[^\"'']+)[\"'']\\s*,\\s*(?P<handler>\\w+)'\n"
           "    - name: express-use\n      when: express\n      path: literal\n      mount: true\n"
           "      regex: '\\bapp\\.use\\(\\s*[\"''](?P<path>[^\"'']+)[\"'']\\s*,\\s*(?P<target>\\w+)'\n"
           "    - name: express-use-bare\n      when: express\n      path: literal\n      mount: true\n"
           "      regex: '\\bapp\\.use\\(\\s*[\"''](?P<path>[^\"'']+)[\"'']\\s*\\)'\n")
SRC = {
    "package.json": '{"name": "api"}\n',
    "src/app.js": "const express = require('express');\nconst app = express();\n"
                  "app.get('/orders', listOrders);\napp.post('/orders', missing);\n"
                  "app.get('/inline', function () {});\napp.use('/v1', router);\napp.use('/bare');\n",
    "src/handlers.js": "function listOrders() { return []; }\nmodule.exports = { listOrders };\n",
}


def build(make_repo, files=SRC, text=EXPRESS):
    repo = make_repo(files)
    with_stack(repo, text)
    return structure.build(repo, "docs/viz-code")


def test_handler_group_resolves_across_files_of_the_module(make_repo):
    s = build(make_repo)
    rs = {(r["method"], r["path"]): r["handler"] for r in s["facts"]["src/app.js"]["routes"]}
    assert rs[("GET", "/orders")] == ".::src/handlers.js#listOrders/0"
    assert all("handler_name" not in r for r in s["facts"]["src/app.js"]["routes"])
    # not found: the span rule's handler stays (the file node here, since no function surrounds the match)
    assert "missing" not in rs[("POST", "/orders")] and rs[("POST", "/orders")] == rs[("GET", "/inline")]


def test_same_file_beats_other_files(make_repo):
    twin = {**SRC, "src/app.js": SRC["src/app.js"] + "function listOrders() {}\n"}
    s = build(make_repo, twin)
    h = next(r["handler"] for r in s["facts"]["src/app.js"]["routes"] if r["path"] == "/orders" and r["method"] == "GET")
    assert h == ".::src/app.js#listOrders/0"


def test_two_candidates_in_one_level_is_ambiguous(make_repo):
    files = {"package.json": SRC["package.json"], "src/app.js": SRC["src/app.js"],
             "src/a.js": "function listOrders() {}\n", "src/b.js": "function listOrders() {}\n"}
    s = build(make_repo, files)
    rs = {(r["method"], r["path"]): r["handler"] for r in s["facts"]["src/app.js"]["routes"]}
    assert rs[("GET", "/orders")] == rs[("GET", "/inline")]   # the span rule's handler


def test_mounts_are_facts_not_routes(make_repo):
    s = build(make_repo)
    f = s["facts"]["src/app.js"]
    assert all(r["path"] not in ("/v1", "/bare") for r in f["routes"])
    assert [(m["path"], m["target"], m["line"]) for m in f["mounts"]] == [("/v1", "router", 6), ("/bare", None, 7)]
    md = structure.summary_md(s)
    assert "- **mounts:** /v1 → router (src/app.js:6); /bare (src/app.js:7)\n" in md
    assert md.index("- **routes:**") < md.index("- **mounts:**")
    pats = {p["name"]: p for p in s["stack"]["patterns"]}
    assert (pats["express-use"]["matches"], pats["express-use"]["mount"]) == (1, True)
    assert "- javascript express-use (stack.yaml): 1 mount in 1 file\n" in md
    assert "- javascript express (stack.yaml): 3 routes in 1 file\n" in md


def test_no_mounts_key_without_matches(make_repo):
    s = build(make_repo, {"package.json": SRC["package.json"], "src/a.js": "const express = require('express');\n"})
    assert "mounts" not in s["facts"]["src/a.js"]


@pytest.mark.parametrize("entry,reason", [
    ("mount: maybe\n      regex: '(?P<path>x)'", "mount must be true or false"),
    ("mount: true\n      regex: '(?P<path>x)(?P<method>y)'", "only path and target"),
    ("mount: true\n      regex: '(?P<target>x)'", "no path group"),
])
def test_mount_validation(tmp_path, entry, reason):
    text = f"javascript:\n  routes:\n    - name: m\n      path: literal\n      {entry}\n"
    with pytest.raises(stack.StackError, match=reason):
        stack.load(write(tmp_path, text))


def test_mount_needs_no_method(tmp_path):
    st = stack.load(write(tmp_path, "javascript:\n  routes:\n    - name: m\n      path: literal\n      mount: true\n"
                          "      regex: '(?P<path>x)'\n"))
    assert next(p for p in st.patterns if p.name == "m").mount is True

