"""code-map.json as assemble writes it: no indentation, one record per line, read back unchanged."""
import json
from pathlib import Path

import assemble as assemble_cli
import extract
from meaning_fixture import MEANING
from vizcode.map import mapjson

SKILL = Path(__file__).resolve().parents[2]
DEMO = SKILL / "demo/parking-city/docs/viz-code/code-map.json"


def _demo() -> dict:
    return json.loads(DEMO.read_text(encoding="utf-8"))


def test_the_text_reads_back_as_the_same_map():
    cmap = _demo()
    assert json.loads(mapjson.dumps(cmap)) == cmap
    assert json.loads(mapjson.dumps({"meta": {}, "nodes": [], "layout": {"containers": {}}})) == \
        {"meta": {}, "nodes": [], "layout": {"containers": {}}}


def test_each_node_relation_floor_and_file_has_a_line_of_its_own():
    cmap = _demo()
    lines = mapjson.dumps(cmap).splitlines()
    records = [json.loads(line.strip().rstrip(",")) for line in lines if line.startswith("  {")]
    assert [r for r in records if r.get("id") in {n["id"] for n in cmap["nodes"]}] == cmap["nodes"]
    assert [r for r in records if "from" in r] == cmap["relations"]
    def entry(line: str) -> dict:   # a `"key":{...}` line as the one-entry object it is
        try:
            return json.loads("{" + line.strip().rstrip(",") + "}")
        except ValueError:
            return {}
    entries = [entry(line) for line in lines]
    assert {k: v for e in entries for k, v in e.items() if k in cmap["layout"]["containers"]} == cmap["layout"]["containers"]
    assert {k: v for e in entries for k, v in e.items() if k in cmap["files"]} == cmap["files"]


def test_it_is_far_smaller_than_indented_json():
    cmap = _demo()
    assert len(mapjson.dumps(cmap)) < 0.85 * len(json.dumps(cmap, indent=1))


def test_assemble_writes_it(shop_repo):
    extract.main([str(shop_repo)])
    (shop_repo / "docs/viz-code/meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    text = (shop_repo / "docs/viz-code/code-map.json").read_text(encoding="utf-8")
    assert text == mapjson.dumps(json.loads(text))
