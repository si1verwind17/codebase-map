"""Pins and examples through the pipeline (format.md § Pins, § Examples): assemble.py refuses and stamps, the map
carries route facts, and the old flows key is refused."""
import copy
import json

import assemble as assemble_cli
import diff as diff_cli
import extract
from conftest import commit_all, write_files
from meaning_fixture import MEANING, RUN
from vizcode import mapcheck, structure
from vizcode.assemble import assemble
from vizcode.fingerprint import entry_fingerprint, type_fingerprint

OUT = ("docs", "viz-code")
ORDER = "orders::orders.models.Order"
CREATE = "orders::orders.main#create/1"


def typed_meaning(**over) -> dict:
    m = {"domain_context": None,
         "nodes": [{"id": "svc:orders", "kind": "service", "name": "orders", "modules": ["orders"],
                    "evidence": [{"file": "docker-compose.yml", "line": 2}]}],
         "relations": [],
         "pins": [{"id": "customer-places-an-order", "title": "customer places an order", "start": CREATE,
                   "direction": "downstream", "by": "agent"}],
         "unpinned": [],
         "examples": {"types": {ORDER: {"value": {"id": "ord-42", "total": 19.9}}},
                      "entries": [{"node": CREATE, "key": "POST /orders", "request": {"id": "ord-42", "total": 19.9},
                                   "response": {"id": "ord-42", "total": 19.9}}]},
         "problems": [], "summaries": {}}
    m.update(over)
    return m


def scan_typed(repo, meaning: dict | None = None) -> dict:
    """extract, write the meaning, assemble (must exit 0), commit the map; returns it."""
    extract.main([str(repo)])
    out = repo.joinpath(*OUT)
    ids = {n["id"] for n in json.loads((out / "structure.json").read_text(encoding="utf-8"))["nodes"]}
    assert {ORDER, CREATE} <= ids, sorted(i for i in ids if "Order" in i or "create" in i)
    (out / "meaning.json").write_text(json.dumps(meaning or typed_meaning()), encoding="utf-8")
    assert assemble_cli.main([str(repo)]) == 0
    commit_all(repo, "add code map")
    return json.loads((out / "code-map.json").read_text(encoding="utf-8"))


def test_assemble_stamps_fingerprints_carries_pins_and_route_facts(typed_repo):
    cmap = scan_typed(typed_repo)
    nodes = {n["id"]: n for n in cmap["nodes"]}
    assert cmap["examples"]["types"][ORDER]["fingerprint"] == type_fingerprint(nodes[ORDER])
    assert cmap["examples"]["entries"][0]["fingerprint"] == entry_fingerprint(nodes[CREATE], nodes)
    assert cmap["pins"] == typed_meaning()["pins"] and cmap["unpinned"] == []
    assert {"method": "POST", "path": "/orders", "handler": CREATE, "line": 9} in cmap["files"]["orders/main.py"]["routes"]
    assert "routes" not in cmap["files"]["orders/models.py"]
    assert list(cmap) == ["meta", "nodes", "relations", "pins", "unpinned", "examples", "files", "problems", "layout"]


def test_a_written_fingerprint_is_overwritten(typed_repo):
    m = typed_meaning()
    m["examples"]["types"][ORDER]["fingerprint"] = "made-up"
    cmap = scan_typed(typed_repo, m)
    assert cmap["examples"]["types"][ORDER]["fingerprint"] != "made-up"


def test_a_written_entry_fingerprint_is_overwritten(typed_repo):
    m = typed_meaning()
    m["examples"]["entries"][0]["fingerprint"] = "made-up"
    cmap = scan_typed(typed_repo, m)
    assert cmap["examples"]["entries"][0]["fingerprint"] != "made-up"


def test_a_value_key_that_is_not_a_field_is_refused(typed_repo):
    m = typed_meaning()
    m["examples"]["types"][ORDER]["value"]["amount"] = 3
    cmap = assemble(structure.build(typed_repo, "docs/viz-code"), m)
    assert (f"example type {ORDER}: amount not among its fields (id, total) — rename or drop them; "
            "a field left out is fine") in mapcheck.check(cmap)


def test_an_empty_meaning_writes_empty_pins_and_examples(shop_repo):
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), {})
    assert (cmap["pins"], cmap["unpinned"], cmap["examples"]) == ([], [], {"types": {}, "entries": []})
    assert mapcheck.check(cmap) == []


def test_meaning_with_flows_is_refused(shop_repo, capsys):
    extract.main([str(shop_repo)])
    (shop_repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps({**MEANING, "flows": []}), encoding="utf-8")
    assert assemble_cli.main([str(shop_repo)]) == 1
    assert "flows: removed from the format" in capsys.readouterr().err


def test_pin_and_example_shapes_are_checked_before_assembling(shop_repo, capsys):
    m = copy.deepcopy(MEANING)
    m["pins"].append({**m["pins"][0], "direction": "sideways"})
    m["examples"]["entries"].append({"node": RUN, "key": "k"})
    extract.main([str(shop_repo)])
    (shop_repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(m), encoding="utf-8")
    assert assemble_cli.main([str(shop_repo)]) == 1
    err = capsys.readouterr().err
    assert "pin worker-job-creates-an-order: direction 'sideways' is not one of downstream, upstream, both" in err
    assert "pin worker-job-creates-an-order: duplicate id (pins 1 and 2)" in err
    assert "example entry 5: needs node (the handler method id), key and request" in err


def test_examples_on_non_methods_and_classes_without_fields_are_refused(shop_repo):
    m = copy.deepcopy(MEANING)
    m["examples"]["types"]["worker::worker.main.Job"] = {"value": {"name": "x"}}   # Job sets self.name: no fields
    m["examples"]["entries"].append({"node": "svc:worker", "key": "GET /x", "request": {}})
    errs = mapcheck.check(assemble(structure.build(shop_repo, "docs/viz-code"), m))
    assert any(e.startswith("example type worker::worker.main.Job: not a class with fields") for e in errs)
    assert "example entry 5 (svc:worker · GET /x): node is not a method — use the handler method's id" in errs


def test_a_pin_may_start_at_a_service_or_a_file_and_a_missing_start_is_not_refused(shop_repo):
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    assert mapcheck.check(cmap) == []
    pin = dict(cmap["pins"][0])
    cmap["pins"] = [{**pin, "start": "svc:worker"}, {**pin, "id": "b", "start": "worker::worker.main"},
                    {**pin, "id": "c", "start": "worker::worker.main#gone/0"}]
    assert mapcheck.check(cmap) == []


def test_the_schema_holds_the_pin_contract(shop_repo):
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    cmap["pins"][0]["by"] = "robot"
    assert any(e.startswith("schema: pins/0/by") for e in mapcheck.check(cmap))
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    cmap["flows"] = []
    assert any(e.startswith("schema: ") and "flows" in e for e in mapcheck.check(cmap))


def test_versions_bumped_for_the_new_format(shop_repo):
    from vizcode import SCANNER_VERSION, SCHEMA_VERSION
    assert (SCHEMA_VERSION, SCANNER_VERSION) == (3, "0.15.0")
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    assert cmap["meta"]["schema_version"] == 3


def test_a_schema_two_map_still_lends_its_layout(shop_repo):
    s = structure.build(shop_repo, "docs/viz-code")
    first = assemble(s, copy.deepcopy(MEANING))
    old = copy.deepcopy(first)
    old["meta"]["schema_version"] = 2
    assert assemble(s, copy.deepcopy(MEANING), old)["layout"] == first["layout"]


def test_a_map_in_the_old_format_gets_a_full_rescan(shop_repo):
    import diff as diff_cli
    extract.main([str(shop_repo)])
    out = shop_repo.joinpath(*OUT)
    (out / "meaning.json").write_text(json.dumps(MEANING), encoding="utf-8")
    assert assemble_cli.main([str(shop_repo)]) == 0
    cmap = json.loads((out / "code-map.json").read_text(encoding="utf-8"))
    cmap["meta"]["schema_version"] = 2                        # as every map made before this plan
    (out / "code-map.json").write_text(json.dumps(cmap), encoding="utf-8")
    commit_all(shop_repo, "a schema-2 map")
    extract.main([str(shop_repo)])
    diff_cli.main([str(shop_repo)])
    stale = json.loads((out / "stale.json").read_text(encoding="utf-8"))
    assert stale["mode"] == "full" and stale["reason"] == "schema version changed: 2 → 3"


def test_malformed_pins_and_examples_are_refused_cleanly(shop_repo, capsys):
    """Shape checks run before the pin and example rules: a wrong-typed block is a fix list, never a traceback."""
    extract.main([str(shop_repo)])
    meaning_file = shop_repo.joinpath(*OUT) / "meaning.json"
    cases = [({"pins": {"a": 1}}, "pins must be a list"),
             ({"unpinned": "x"}, "unpinned must be a list"),
             ({"examples": []}, "examples must be an object"),
             ({"examples": None}, "examples must be an object (got null)"),
             ({"pins": ["x", None]}, "pin 1: must be an object {id, title, start, direction, by}"),
             ({"unpinned": [3]}, "unpinned 1: must be a pin id (a string)"),
             ({"examples": {"types": [], "entries": {}}}, "examples.types must be an object keyed by class id"),
             ({"examples": {"types": {"x": 1}, "entries": [7]}}, "example type x: needs a value object"),
             ({"examples": {"types": {}, "entries": [7]}}, "example entry 1: needs node")]
    for over, msg in cases:
        meaning_file.write_text(json.dumps({**MEANING, **over}), encoding="utf-8")
        assert assemble_cli.main([str(shop_repo)]) == 1, over
        assert msg in capsys.readouterr().err, over


def rescan(repo):
    extract.main([str(repo)])
    diff_cli.main([str(repo)])
    out = repo.joinpath(*OUT)
    meaning = json.loads((out / "meaning.json").read_text(encoding="utf-8")) if (out / "meaning.json").exists() else None
    return json.loads((out / "stale.json").read_text(encoding="utf-8")), meaning


def test_a_comment_only_edit_keeps_examples_fresh(typed_repo):
    before = scan_typed(typed_repo)
    write_files(typed_repo, {"orders/main.py": (typed_repo / "orders/main.py").read_text() + "\n# touched\n"})
    commit_all(typed_repo, "touch main")
    stale, meaning = rescan(typed_repo)
    assert stale["mode"] == "incremental" and stale["stale_examples"] == []
    assert meaning["examples"] == before["examples"]
    assert meaning["pins"] == before["pins"] and meaning["unpinned"] == []   # pins carry over unchanged


def test_a_changed_field_type_flags_the_type_and_the_entry_that_refers_to_it(typed_repo, capsys):
    before = scan_typed(typed_repo)
    write_files(typed_repo, {"orders/models.py": (typed_repo / "orders/models.py").read_text().replace(
        "total: float", "total: int")})
    commit_all(typed_repo, "total in cents")
    stale, meaning = rescan(typed_repo)
    assert stale["mode"] == "incremental"
    assert stale["stale_examples"] == [{"type": ORDER, "why": "its fields changed"},
                                       {"entry": CREATE, "key": "POST /orders",
                                        "why": "its handler's signature, or a type it takes or returns, changed"}]
    assert meaning["examples"]["types"][ORDER]["stale"] is True
    assert meaning["examples"]["entries"][0]["stale"] is True
    capsys.readouterr()
    assert assemble_cli.main([str(typed_repo)]) == 1
    err = capsys.readouterr().err
    assert f"example type {ORDER}: stale — rewrite its value" in err
    assert f"example entry 1 ({CREATE} · POST /orders): stale" in err
    # the agent rewrites the values and drops the flags
    meaning["examples"]["types"][ORDER] = {"value": {"id": "ord-42", "total": 1990}}
    meaning["examples"]["entries"][0] = {"node": CREATE, "key": "POST /orders",
                                         "request": {"id": "ord-42", "total": 1990},
                                         "response": {"id": "ord-42", "total": 1990}}
    (typed_repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(meaning), encoding="utf-8")
    assert assemble_cli.main([str(typed_repo)]) == 0
    after = json.loads((typed_repo.joinpath(*OUT) / "code-map.json").read_text(encoding="utf-8"))
    assert after["examples"]["types"][ORDER]["fingerprint"] != before["examples"]["types"][ORDER]["fingerprint"]


def test_a_removed_class_flags_its_type_example(typed_repo):
    scan_typed(typed_repo)
    write_files(typed_repo, {"orders/models.py": "from dataclasses import dataclass\n\n\n@dataclass\n"
                                                 "class Invoice:\n    id: str\n"})
    commit_all(typed_repo, "order is gone")
    stale, meaning = rescan(typed_repo)
    assert {"type": ORDER, "why": "the class is gone"} in stale["stale_examples"]
    assert meaning["examples"]["types"][ORDER]["stale"] is True


def test_a_full_rescan_flags_examples_in_the_previous_meaning(typed_repo, capsys):
    scan_typed(typed_repo)
    write_files(typed_repo, {
        "docker-compose.yml": "services:\n  orders: {build: .}\n  billing: {build: ./billing}\n",   # a full rescan
        "orders/models.py": (typed_repo / "orders/models.py").read_text().replace("total: float", "total: int")})
    commit_all(typed_repo, "deploy and type change")
    capsys.readouterr()
    stale, meaning = rescan(typed_repo)
    assert stale["mode"] == "full" and meaning is None
    prev = json.loads((typed_repo.joinpath(*OUT) / "meaning.previous.json").read_text(encoding="utf-8"))
    assert prev["examples"]["types"][ORDER]["stale"] is True
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["previous_stale"] >= 2


def test_assemble_refuses_while_a_full_rescan_waits_for_its_previous_meaning(shop_repo, capsys):
    """After a full rescan diff.py leaves meaning.previous.json and no meaning.json: assembling then would write a
    map with no services over the last one and delete the only copy of its meaning."""
    extract.main([str(shop_repo)])
    out = shop_repo / "docs/viz-code"
    (out / "meaning.previous.json").write_text('{"nodes": [], "relations": []}', encoding="utf-8")
    assert assemble_cli.main([str(shop_repo)]) == 1
    assert "meaning.previous.json" in capsys.readouterr().err
    assert (out / "meaning.previous.json").exists() and not (out / "code-map.json").exists()


def test_assemble_refuses_evidence_past_a_files_end_or_on_a_blank_line(typed_repo, capsys):
    extract.main([str(typed_repo)])
    out = typed_repo.joinpath(*OUT)
    m = typed_meaning()
    m["nodes"][0]["evidence"] = [{"file": m["nodes"][0]["evidence"][0]["file"], "line": 9999},
                                 {"file": "no/such/file.py", "line": 1}]
    (out / "meaning.json").write_text(json.dumps(m), encoding="utf-8")
    assert assemble_cli.main([str(typed_repo)]) == 1
    err = capsys.readouterr().err
    assert ":9999 is past the end of the file" in err and "no/such/file.py:1: no such file at" in err
