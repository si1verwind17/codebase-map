"""examples.py: the checklist of examples a map should have, totals first, each ok, missing or stale."""
import json

import examples as examples_cli
from examples_fixture import CREATE, ORDER, cmap

EXPECTED_EMPTY = """\
Entry points: 2 (2 without an example)
- missing  m::m.api#consume/1  orders
- missing  m::m.api#create/1  POST /orders
Data types: 4 (4 without an example)
- missing  m::m.models.Line  fields: sku  — within 2 hops of pin customer-orders
- missing  m::m.models.Order  fields: id, total  — entry point m::m.api#create/1; within 2 hops of pin customer-orders
- missing  m::m.models.Receipt  fields: paid  — within 2 hops of pin customer-orders
- missing  m::m.models.Row  fields: n  — within 2 hops of pin who-reads-orders
"""


def test_report_on_a_map_without_examples():
    assert examples_cli.report(cmap(), None) == EXPECTED_EMPTY


def test_report_reads_pins_and_examples_from_meaning_when_given():
    meaning = {"pins": [],
               "examples": {"types": {ORDER: {"value": {}, "stale": True}},
                            "entries": [{"node": CREATE, "key": "POST /orders", "request": {}}]}}
    assert examples_cli.report(cmap(), meaning) == """\
Entry points: 2 (1 without an example)
- missing  m::m.api#consume/1  orders
- ok       m::m.api#create/1  POST /orders
Data types: 1 (0 without an example)
- stale    m::m.models.Order  fields: id, total  — entry point m::m.api#create/1
"""


def test_main_needs_a_map(tmp_path, capsys):
    (tmp_path / "repo").mkdir()
    assert examples_cli.main([str(tmp_path / "repo")]) == 2
    assert "run assemble.py first" in capsys.readouterr().err


def test_main_prints_the_report(tmp_path, capsys):
    out = tmp_path / "repo" / "docs" / "viz-code"
    out.mkdir(parents=True)
    (out / "code-map.json").write_text(json.dumps(cmap()), encoding="utf-8")
    assert examples_cli.main([str(tmp_path / "repo")]) == 0
    assert capsys.readouterr().out == EXPECTED_EMPTY


def test_a_method_with_several_keys_shows_how_many_have_an_example():
    m = cmap()
    m["files"]["m/api.py"]["routes"].append({"method": "PUT", "path": "/orders", "handler": CREATE, "line": 5})
    meaning = {"pins": [], "examples": {"types": {}, "entries": [{"node": CREATE, "key": "POST /orders",
                                                                  "request": {}}]}}
    out = examples_cli.report(m, meaning)
    assert out.startswith("Entry points: 2 (1 without an example, 1 missing some keys)\n")
    assert "- missing 1/2 keys  m::m.api#create/1  POST /orders; PUT /orders" in out
    meaning["examples"]["entries"][0]["stale"] = True
    assert "- stale, missing 1/2 keys  m::m.api#create/1" in examples_cli.report(m, meaning)
    del meaning["examples"]["entries"][0]["stale"]
    meaning["examples"]["entries"].append({"node": CREATE, "key": "PUT /orders", "request": {}})
    assert "- ok       m::m.api#create/1  POST /orders; PUT /orders" in examples_cli.report(m, meaning)


def test_an_example_whose_key_is_no_longer_the_methods_is_flagged():
    meaning = {"pins": [], "examples": {"types": {}, "entries": [{"node": CREATE, "key": "POST /old",
                                                                  "request": {}}]}}
    out = examples_cli.report(cmap(), meaning)
    assert "- ok, key gone: POST /old  m::m.api#create/1  POST /orders" in out


def test_over_the_entry_threshold_only_entry_points_on_a_pin_need_one(monkeypatch):
    """Above ALL_ENTRIES entry points, those a pin's trace reaches need an example; the rest are listed, optional,
    and the audit asks for none of them."""
    from vizcode import examples, mapcheck
    monkeypatch.setattr(examples, "ALL_ENTRIES", 1)
    out = examples_cli.report(cmap(), None)
    assert out.splitlines()[:3] == [
        "Entry points: 1 (1 without an example); the map has 2, over 1: only those on a pin's trace need one, "
        "the other 1 are listed last as optional",
        "- missing  m::m.api#create/1  POST /orders", "- optional  m::m.api#consume/1  orders"]
    assert [w["node"] for w in mapcheck.warnings(cmap()) if w["id"] == "example.missing"] == [CREATE]


def test_a_class_whose_fields_are_all_collaborators_is_marked_wiring():
    from vizcode import examples
    nodes = {"a.Svc": {"fields": [{"name": "repo", "type": "OrderRepository"}, {"name": "log", "type": "Logger"}]},
             "a.Order": {"fields": [{"name": "id", "type": "UUID"}, {"name": "client", "type": "HttpClient"}]}}
    assert examples.wiring("a.Svc", nodes) and not examples.wiring("a.Order", nodes)
