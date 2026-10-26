from vizcode import ids
from vizcode.scan import structure
from vizcode.scan.adapters import generic
from vizcode.scan.adapters.langs import BY_SUFFIX, SPECS

JS = SPECS["javascript"]
MOD = {"id": "mod:api", "path": "api", "lang": "javascript", "build": "dir"}
FILE = "api/src/repo.js"
GOLDEN = """const express = require("express");
const { join } = require("path");
import { x } from "../lib/x.js";
export { y } from "./y";

class Repo extends Base {
  #secret() {}
  handle = (req) => req;
  static go(a, b = 2, ...c) { return fetch(`${a}/x`); }
}

function list(req, res) { res.json([]); }
const make = () => new Repo();
exports.handler = async (event) => list(event);
module.exports = { Repo, list };
"""
REPO = "api::src.repo.Repo"
FILE_ID = "api::src/repo.js"


def parse(src: str, rel: str = FILE):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=JS)


def test_javascript_spec_registered():
    assert all(BY_SUFFIX[s] is JS for s in (".js", ".jsx", ".mjs", ".cjs"))
    assert JS.grammar == "javascript" and JS.package == "dir" and JS.sep == "/"
    assert structure.LANGS[".mjs"][0] == "javascript"


def test_javascript_nodes():
    res = parse(GOLDEN)
    assert res["package"] == "src"
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        (REPO, "class", "Repo", "api::src/", 6, "public"),
        (f"{REPO}##secret/0", "method", "#secret", REPO, 7, "private"),
        (f"{REPO}#handle/1", "method", "handle", REPO, 8, "public"),
        (f"{REPO}#go/3", "method", "go", REPO, 9, "public"),
        (FILE_ID, "file", "repo.js", "api::src/", 1, "public"),
        (f"{FILE_ID}#list/2", "method", "list", FILE_ID, 12, "public"),
        (f"{FILE_ID}#make/0", "method", "make", FILE_ID, 13, "public"),
        # `exports.handler = async (event) => ...`: the function is named after the property
        (f"{FILE_ID}#handler/1", "method", "handler", FILE_ID, 14, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    # bare identifiers are parameters named by their own text
    assert n[f"{REPO}#go/3"]["signature"] == {"params": [{"name": "a", "type": None}, {"name": "b", "type": None},
                                                         {"name": "*c", "type": None}], "returns": None}
    assert n[f"{FILE_ID}#list/2"]["signature"]["params"] == [{"name": "req", "type": None},
                                                             {"name": "res", "type": None}]
    assert res["supers"] == [(REPO, ["Base"])]


def test_javascript_facts():
    res = parse(GOLDEN)
    assert res["imports"] == [
        {"target": "express", "line": 1, "relative": False, "names": []},
        {"target": "path", "line": 2, "relative": False, "names": []},
        {"target": "../lib/x.js", "line": 3, "relative": True, "names": ["x"]},
        {"target": "./y", "line": 4, "relative": True, "names": ["y"]},
    ]
    assert res["calls"] == [
        {"callee": "fetch", "in": f"{REPO}#go/3", "line": 9, "args": 1},
        {"callee": "res.json", "in": f"{FILE_ID}#list/2", "line": 12, "args": 1},
        {"callee": "Repo", "in": f"{FILE_ID}#make/0", "line": 13, "args": 0},
        {"callee": "list", "in": f"{FILE_ID}#handler/1", "line": 14, "args": 1},
    ]
    assert res["strings"] == [{"text": "{a}/x", "line": 9, "in": f"{REPO}#go/3"}]


def test_javascript_mixin_super_is_not_a_name():
    res = parse("class A extends mixin(B) {}\n", "api/a.js")
    assert res["supers"] == []


def test_javascript_non_ascii():
    res = parse('const grüße = () => "Grüße";\n', "api/g.js")
    assert [n["id"] for n in res["nodes"]] == ["api::_root_/g.js", "api::_root_/g.js#grüße/0"]
    assert res["strings"] == [{"text": "Grüße", "line": 1, "in": "api::_root_/g.js#grüße/0"}]


def test_javascript_survives_broken_file():
    src = "function fine() { go(); }\n\nfunction half(x) {\n  call(\n"
    res = parse(src, "api/b.js")
    assert res["parse_error"] is True
    assert "api::_root_/b.js#fine/0" in [n["id"] for n in res["nodes"]]
    assert {"callee": "go", "in": "api::_root_/b.js#fine/0", "line": 1, "args": 0} in res["calls"]


def test_javascript_end_to_end(make_repo):
    repo = make_repo({"api/src/repo.js": GOLDEN, "api/src/index.mjs": 'import { list } from "./repo.js";\n'})
    s = structure.build(repo)
    assert s["files"]["api/src/repo.js"]["lang"] == "javascript"
    assert s["files"]["api/src/index.mjs"]["lang"] == "javascript"


def test_javascript_destructured_and_default_parameter_names():
    """A destructured or default parameter is named by its key or left side, never by its default value."""
    res = parse("function f({ b: c }, {a} = foo, [x, y], d = bar, {e = 1}) {}\n", "api/d.js")
    sig = res["nodes"][-1]["signature"]
    assert [p["name"] for p in sig["params"]] == ["b", "a", "x", "d", "e"]
