import json
from pathlib import Path

from vizcode import findings

DEMO = Path(__file__).resolve().parents[2] / "demo/parking-city/docs/viz-code/code-map.json"


def node(i, kind, parent=None):
    return {"id": i, "kind": kind, "name": i, **({"parent": parent} if parent else {})}


def rel(a, b, kind="request"):
    return {"id": f"r:{kind}:{a}->{b}", "kind": kind, "from": a, "to": b}


def cmap(rels, extra=()):
    nodes = [node(s, "service") for s in "ABC"] + list(extra)
    return {"nodes": nodes, "relations": rels}


def test_two_loop_once():
    got = findings.cycles(cmap([rel("A", "B"), rel("B", "A")]))
    assert got == [{"services": ["A", "B"], "relations": ["r:request:A->B", "r:request:B->A"], "others": []}]


def test_three_loop_once():
    got = findings.cycles(cmap([rel("A", "B"), rel("B", "C"), rel("C", "A", "stream")]))
    assert [c["services"] for c in got] == [["A", "B", "C"]]
    assert len(got[0]["relations"]) == 3


def test_a_bigger_group_names_the_services_off_the_loop():
    got = findings.cycles(cmap([rel("A", "B"), rel("B", "A"), rel("A", "C"), rel("C", "A")]))
    assert got == [{"services": ["A", "B"], "relations": ["r:request:A->B", "r:request:B->A"], "others": ["C"]}]


def test_event_edges_are_ignored():
    m = cmap([rel("A", "T", "event"), rel("T", "B", "event"), rel("B", "A")], [node("T", "topic")])
    assert findings.cycles(m) == []


def test_method_ends_roll_up():
    extra = [node("pa", "package", "A"), node("ma", "method", "pa"), node("mb", "method", "B")]
    got = findings.cycles(cmap([rel("ma", "mb"), rel("B", "A")], extra))
    assert [c["services"] for c in got] == [["A", "B"]]


def test_no_services_or_relations():
    assert findings.cycles({"nodes": [], "relations": []}) == []
    assert findings.cycles({"nodes": [node("L", "library")], "relations": [rel("L", "L")]}) == []
    assert findings.cycles(cmap([])) == []


def test_demo_cycles_recorded():
    got = findings.cycles(json.loads(DEMO.read_text()))
    assert isinstance(got, list)
    assert got == DEMO_CYCLES


DEMO_CYCLES: list = []
