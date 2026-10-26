import copy

from meaning_fixture import MEANING, POST, WRITE

from vizcode.map import mapcheck
from vizcode.scan import structure
from vizcode.map.assemble import assemble
from vizcode.layout.direction import apply_defaults, oriented


def test_data_defaults_and_orientation():
    rels = [{"kind": "db-read", "from": "s", "to": "t"}, {"kind": "stream", "from": "s", "to": "x"},
            {"kind": "request", "from": "a", "to": "b", "data": "forward"}]
    apply_defaults(rels)
    assert [r.get("data") for r in rels] == ["back", None, "forward"]
    assert oriented(rels[0]) == ("t", "s") and oriented(rels[2]) == ("a", "b")


def test_assembled_relations_carry_data_direction(shop_repo):
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    rels = {r["id"]: r for r in cmap["relations"]}
    assert rels[POST]["data"] == "forward" and rels[WRITE]["data"] == "forward"   # a request: from the caller
    assert mapcheck.check(cmap) == []


def test_stream_without_direction_is_rejected(shop_repo):
    meaning = copy.deepcopy(MEANING)
    meaning["nodes"].append({"id": "3p:feed", "kind": "external", "name": "feed"})
    meaning["relations"].append({"kind": "stream", "from": "svc:worker", "to": "3p:feed", "key": "wss://feed",
                                 "confidence": "confirmed", "evidence": [{"file": "worker/main.py", "line": 1}]})
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), meaning)
    assert any("stream needs a data direction" in e for e in mapcheck.check(cmap))
