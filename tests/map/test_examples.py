"""Examples (format.md § Examples): entry points, the types a map should have examples for, the refusals, the
fingerprints assemble.py stamps and the staleness diff.py flags."""
import copy
import json
from pathlib import Path

from examples_fixture import (AUDIT, BARE, CONSUME, CREATE, LINE, LOG, ORDER, PRICE, READ, RECEIPT, ROW, TABLE, TAX,
                              cmap, method, rel)
from vizcode import examples
from vizcode.fingerprint import entry_fingerprint, type_fingerprint


def nodes(m):
    return {n["id"]: n for n in m["nodes"]}


def test_entry_points_from_routes_and_relations():
    assert examples.entry_points(cmap()) == {CONSUME: ["orders"], CREATE: ["POST /orders"]}


def test_entry_points_skip_handlers_that_are_not_methods():
    m = cmap()   # /health's handler is the file node; the request ends at a service
    assert "m::m.api" not in examples.entry_points(m) and "svc:m" not in examples.entry_points(m)


def test_a_method_serving_several_routes_lists_every_key():
    m = cmap()
    m["files"]["m/api.py"]["routes"].append({"method": "GET", "path": "/orders/{id}", "handler": CREATE, "line": 5})
    m["relations"].append({"id": "r:batch", "kind": "batch", "from": "svc:m", "to": CREATE, "key": "task nightly",
                           "confidence": "confirmed", "evidence": [{"file": "m/api.py", "line": 1}]})
    assert examples.entry_points(m)[CREATE] == ["GET /orders/{id}", "POST /orders", "task nightly"]


def test_a_route_is_one_key_whatever_its_spelling():
    m = cmap()   # files list POST /orders without its mount; the request relation writes it with /v1
    m["relations"].append({"id": "r:req", "kind": "request", "from": "svc:m", "to": CREATE, "key": "POST /v1/orders",
                           "confidence": "confirmed", "evidence": [{"file": "m/api.py", "line": 3}]})
    assert examples.entry_points(m)[CREATE] == ["POST /v1/orders"]
    m["relations"][-1]["key"] = "GET /v1/orders"          # another method: another route
    assert examples.entry_points(m)[CREATE] == ["GET /v1/orders", "POST /orders"]


def test_downstream_two_hops_and_db_read_runs_table_to_reader():
    assert examples.downstream(cmap(), CREATE) == [CREATE, PRICE, TAX]          # log is 3 hops away
    assert examples.downstream(cmap(), TABLE) == [TABLE, READ]                  # a table's downstream is its readers
    assert examples.downstream(cmap(), READ) == [READ]                          # the reader does not lead to the table


def test_downstream_of_a_datastore_starts_at_its_tables_else_at_itself():
    m = cmap()
    m["nodes"].append({"id": "db:postgres:DB_HOST", "kind": "datastore", "name": "DB_HOST"})
    assert examples.downstream(m, "db:postgres:DB_HOST") == [TABLE, READ]       # its reads and writes are on the tables
    m["nodes"].append({"id": "db:redis:R", "kind": "datastore", "name": "R"})
    assert examples.downstream(m, "db:redis:R") == ["db:redis:R"]               # no tables: the datastore itself


def test_wanted_types_come_from_entry_handlers_and_two_hops_below_each_pin():
    want = examples.wanted(cmap())
    assert want["entries"] == {CONSUME: ["orders"], CREATE: ["POST /orders"]}
    assert want["types"] == {
        LINE: ["within 2 hops of pin customer-orders"],
        ORDER: ["entry point m::m.api#create/1", "within 2 hops of pin customer-orders"],
        RECEIPT: ["within 2 hops of pin customer-orders"],
        ROW: ["within 2 hops of pin who-reads-orders"],
    }
    assert AUDIT not in want["types"] and BARE not in want["types"]   # 3 hops away; no fields


def test_wanted_takes_the_pins_it_is_given():
    assert examples.wanted(cmap(), pins=[])["types"] == {ORDER: ["entry point m::m.api#create/1"]}


def test_shape_errors():
    assert examples.shape_errors({}) == []
    assert examples.shape_errors({"types": [], "entries": {}}) == [
        "examples.types must be an object keyed by class id", "examples.entries must be a list"]
    assert examples.shape_errors({"types": {ORDER: {"value": 3}}, "entries": [{"node": CREATE, "key": "k"}]}) == [
        f"example type {ORDER}: needs a value object whose keys are the class's field names",
        "example entry 1: needs node (the handler method id), key and request"]


def test_check_accepts_a_value_with_fields_left_out():
    m = cmap()
    m["examples"] = {"types": {ORDER: {"value": {"id": "ord-1"}}},
                     "entries": [{"node": CREATE, "key": "POST /orders", "request": {}, "response": {}},
                                 {"node": CREATE, "key": "GET /orders/{id}", "request": {}}]}
    assert examples.check(m) == []


def test_check_refusals():
    m = cmap()
    m["examples"] = {
        "types": {BARE: {"value": {}}, "m::m.models.Nope": {"value": {}},
                  ORDER: {"value": {"id": "ord-1", "amount": 3}}, LINE: {"value": {}, "stale": True}},
        "entries": [{"node": "svc:m", "key": "GET /nowhere", "request": {}},
                    {"node": CREATE, "key": "POST /orders", "request": {}},
                    {"node": CREATE, "key": "POST /orders", "request": {}, "stale": True}]}
    errs = examples.check(m)
    assert f"example type {BARE}: not a class with fields" in errs[0]
    assert "example type m::m.models.Nope: not a class with fields" in errs[1]
    assert errs[2] == (f"example type {ORDER}: amount not among its fields (id, total) — rename or drop them; "
                       "a field left out is fine")
    assert errs[3].startswith(f"example type {LINE}: stale — rewrite its value")
    assert errs[4] == "example entry 1 (svc:m · GET /nowhere): node is not a method — use the handler method's id"
    assert errs[5].startswith(f"example entry 3 ({CREATE} · POST /orders): stale")
    assert errs[6].startswith(f"example entry 3 ({CREATE} · POST /orders): duplicates an earlier entry example")
    assert len(errs) == 7


def test_stamped_overwrites_a_written_fingerprint_and_skips_what_is_missing():
    m = cmap()
    ex = {"types": {ORDER: {"value": {"id": "x"}, "fingerprint": "made-up"}, "m::m.models.Nope": {"value": {}}},
          "entries": [{"node": CREATE, "key": "POST /orders", "request": {}, "fingerprint": "made-up"},
                      {"node": "svc:m", "key": "k", "request": {}}]}
    got = examples.stamped(ex, nodes(m))
    assert got["types"][ORDER]["fingerprint"] == type_fingerprint(nodes(m)[ORDER])
    assert got["entries"][0]["fingerprint"] == entry_fingerprint(nodes(m)[CREATE], nodes(m))
    assert "fingerprint" not in got["types"]["m::m.models.Nope"] and "fingerprint" not in got["entries"][1]
    assert ex["types"][ORDER]["fingerprint"] == "made-up"   # the input is not changed


def test_flag_stale_by_fingerprint_and_by_gone_nodes():
    m = cmap()
    ex = examples.stamped({"types": {ORDER: {"value": {}}, LINE: {"value": {}}},
                           "entries": [{"node": CREATE, "key": "POST /orders", "request": {}},
                                       {"node": CONSUME, "key": "orders", "request": {}}]}, nodes(m))
    same, flagged = examples.flag_stale(ex, nodes(m))
    assert flagged == [] and same == ex
    new = copy.deepcopy(m)
    nodes(new)[ORDER]["fields"][1]["type"] = "int"                 # Order.total changed type
    new["nodes"] = [n for n in new["nodes"] if n["id"] not in (LINE, CONSUME)]   # Line and consume are gone
    got, flagged = examples.flag_stale(ex, nodes(new))
    assert flagged == [{"type": ORDER, "value_lacks": ["id", "total"]}, {"type": LINE},
                       {"entry": CREATE, "key": "POST /orders"}, {"entry": CONSUME, "key": "orders"}]
    assert got["types"][ORDER]["stale"] is True and got["entries"][0]["stale"] is True
    assert "stale" not in ex["types"][ORDER]   # the input is not changed


def test_a_stale_type_names_the_fields_its_value_lacks_and_the_keys_no_longer_fields():
    m = cmap()
    ex = examples.stamped({"types": {ORDER: {"value": {"id": "o-1", "total": 9.5}}}, "entries": []}, nodes(m))
    new = copy.deepcopy(m)
    nodes(new)[ORDER]["fields"] = [{"name": "id", "type": "str"}, {"name": "renewals", "type": "int"}]
    _, flagged = examples.flag_stale(ex, nodes(new))
    assert flagged == [{"type": ORDER, "value_lacks": ["renewals"], "value_extra": ["total"]}]


def test_an_unflagged_example_stays_the_same_object_shape():
    m = cmap()
    ex = examples.stamped({"types": {ROW: {"value": {"n": 1}}}, "entries": []}, nodes(m))
    got, _ = examples.flag_stale(ex, nodes(m))
    assert got == {"types": {ROW: {"value": {"n": 1}, "fingerprint": type_fingerprint(nodes(m)[ROW])}},
                   "entries": []}


def test_log_is_never_wanted_but_can_hold_an_example():
    m = cmap()
    m["examples"] = {"types": {AUDIT: {"value": {"at": "2026-10-13T08:00:00Z"}}}, "entries": [
        {"node": LOG, "key": "internal", "request": {}}]}
    assert examples.check(m) == []


def test_a_trait_method_reaches_its_implementations_at_no_hop_cost():
    m = cmap()
    trait, impl = "m::m.api.Pricer", "m::m.api.FlatPricer"
    t_run, i_run = "m::m.api.Pricer#run/1", "m::m.api.FlatPricer#run/1"
    m["nodes"] += [{"id": trait, "kind": "class", "parent": "m::m.api", "name": "Pricer"},
                   {"id": impl, "kind": "class", "parent": "m::m.api", "name": "FlatPricer", "implements": [trait]},
                   {**method(t_run), "parent": trait}, {**method(i_run, (AUDIT,)), "parent": impl}]
    m["relations"] += [rel("calls", CREATE, t_run), rel("calls", i_run, LOG)]
    m["pins"] = [{"id": "p", "title": "p", "start": CREATE, "direction": "downstream", "by": "agent"}]
    # create -> trait run (1 hop); the implementation rides along at that distance, so log is 2 hops away
    assert examples.downstream(m, CREATE) == [CREATE, PRICE, i_run, t_run, LOG, TAX]
    assert AUDIT in examples.wanted(m)["types"]       # the implementation's refs count as wanted
    assert examples.downstream(cmap(), CREATE) == [CREATE, PRICE, TAX]


def test_an_implementation_with_another_arity_is_followed_when_it_is_the_only_one():
    m = cmap()
    trait, impl = "m::m.api.Pricer", "m::m.api.FlatPricer"
    t_run, i_run = "m::m.api.Pricer#run/1", "m::m.api.FlatPricer#run/2"   # no same-arity method: any arity
    m["nodes"] += [{"id": trait, "kind": "class", "parent": "m::m.api", "name": "Pricer"},
                   {"id": impl, "kind": "class", "parent": "m::m.api", "name": "FlatPricer", "implements": [trait]},
                   {**method(t_run), "parent": trait}, {**method(i_run), "parent": impl}]
    m["relations"] += [rel("calls", CREATE, t_run)]
    assert i_run in examples.downstream(m, CREATE)


DEMO = Path(__file__).resolve().parents[2] / "demo/parking-city/docs/viz-code/code-map.json"
# the same expectations as viewer/test/trace_seeds.test.ts: the viewer and this checklist seed a container alike
FEATURE_STORE = ["features::features.workflows#compute_zone_features/1", "features::features.workflows#features_wf/1"]
COMMON = ["common::city.parking.common.Config$#env/1", "common::city.parking.common.EventProducer#publish/3",
          "common::city.parking.common.Jdbc#query/3", "common::city.parking.common.Jdbc#transaction/1",
          "common::city.parking.common.Jdbc#update/2"]


def shelf() -> dict:
    """A library x (util.a called from outside, util.b only from a, util.c linked by code only, empty.py with nothing)
    and a service y whose run calls a."""
    def node(i, kind, parent=None):
        return {"id": i, "kind": kind, "name": i.rsplit("#", 1)[-1].rsplit(".", 1)[-1], **({"parent": parent} if parent else {})}
    return {
        "nodes": [node("lib:x", "library"), node("x::x/", "package", "lib:x"), node("x::x.util", "file", "x::x/"),
                  node("x::x.util#a/0", "method", "x::x.util"), node("x::x.util#b/0", "method", "x::x.util"),
                  node("x::x.util#c/0", "method", "x::x.util"), node("x::x.empty", "file", "x::x/"),
                  node("svc:y", "service"), node("y::y/", "package", "svc:y"), node("y::y.main", "file", "y::y/"),
                  node("y::y.main#run/0", "method", "y::y.main")],
        "relations": [rel("calls", "y::y.main#run/0", "x::x.util#a/0"), rel("calls", "x::x.util#a/0", "x::x.util#b/0"),
                      rel("uses-code", "x::x.util#c/0", "y::y.main#run/0")],
        "files": {},
    }


def test_seeds_of_the_demo_match_the_viewer():
    m = json.loads(DEMO.read_text(encoding="utf-8"))
    assert examples.seeds(m, "svc:feature-store") == FEATURE_STORE     # its entry points
    assert examples.seeds(m, "lib:common") == COMMON                   # none: its boundary methods


def test_seeds_entry_points_else_boundary_methods_else_itself():
    m = shelf()
    assert examples.seeds(m, "lib:x") == ["x::x.util#a/0"]             # a call from outside; b is inside, c a code link
    assert examples.seeds(m, "y::y.main") == ["y::y.main#run/0"]       # run reaches outside
    assert examples.seeds(m, "x::x.empty") == ["x::x.empty"]           # nothing: the container itself
    m["relations"].append(rel("event", "topic:t", "x::x.util#b/0", "t"))
    assert examples.seeds(m, "lib:x") == ["x::x.util#b/0"]             # an entry point wins
    assert examples.seeds(m, "x::x.util#a/0") == ["x::x.util#a/0"]     # a method is its own seed


def test_downstream_of_a_container_walks_from_its_seeds():
    assert examples.downstream(shelf(), "lib:x") == ["x::x.util#a/0", "x::x.util#b/0"]
