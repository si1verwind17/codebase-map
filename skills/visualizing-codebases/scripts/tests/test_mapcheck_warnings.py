import copy
import json
from pathlib import Path

from vizcode import examples, mapcheck

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo/parking-city/docs/viz-code"
DEMO = json.loads((DEMO_DIR / "code-map.json").read_text())
SUMMARY = (DEMO_DIR / "summary.md").read_text() if (DEMO_DIR / "summary.md").exists() else None


def ids(ws):
    return sorted(w["id"] for w in ws)


def test_empty_map():
    assert mapcheck.warnings({"nodes": [], "relations": []}) == []
    assert mapcheck.warnings({"nodes": [], "relations": []}, "- **env keys:** X_URL\n") == [
        {"id": "ext.missing", "node": None,
         "detail": "config key X_URL looks like an outside endpoint but nothing in the map names X_URL"}]


def test_demo_warnings_recorded():
    # recorded, not special-cased: packages named like their service or library no longer warn (spec 2.5)
    assert [w["node"] for w in mapcheck.warnings(DEMO)] == []
    if SUMMARY is not None:
        ext = [w["detail"].split()[2] for w in mapcheck.warnings(DEMO, SUMMARY) if w["id"] == "ext.missing"]
        assert ext == []


def test_ext_missing_and_covered():
    m = copy.deepcopy(DEMO)
    s = "- **env keys:** PAYROLL_API_KEY; FINES_API_URL; DB_HOST; DEBUG; PAYROLL_API_KEY\n"
    w = [x for x in mapcheck.warnings(m, s) if x["id"] == "ext.missing"]
    assert [x["detail"].split()[2] for x in w] == ["PAYROLL_API_KEY"]
    assert all(x["node"] is None for x in w)


def test_name_container_stops_at_the_module():
    m = copy.deepcopy(DEMO)
    pkg = next(n for n in m["nodes"] if n["kind"] == "package")
    parent = next(n for n in m["nodes"] if n["id"] == pkg["parent"])
    assert parent["kind"] in ("service", "library")
    pkg["name"] = parent["name"]
    assert [w for w in mapcheck.warnings(m) if w["id"] == "name.container"] == []


def test_name_container_class_named_like_its_package():
    m = copy.deepcopy(DEMO)
    cls = next(n for n in m["nodes"] if n["kind"] == "class" and n["parent"] in {p["id"] for p in m["nodes"] if p["kind"] == "package"})
    parent = next(n for n in m["nodes"] if n["id"] == cls["parent"])
    cls["name"] = parent["name"]
    got = [w for w in mapcheck.warnings(m) if w["id"] == "name.container"]
    assert [w["node"] for w in got] == [cls["id"]]


def test_name_container_package_under_package():
    m = copy.deepcopy(DEMO)
    pkg = next(n for n in m["nodes"] if n["kind"] == "package")
    child = {"id": pkg["id"] + "x", "kind": "package", "name": pkg["name"], "parent": pkg["id"]}
    m["nodes"].append(child)
    got = [w for w in mapcheck.warnings(m) if w["id"] == "name.container"]
    assert [w["node"] for w in got] == [child["id"]]


def test_module_empty():
    m = copy.deepcopy(DEMO)
    m["nodes"].append({"id": "svc:ghost", "kind": "service", "name": "ghost"})
    got = [w for w in mapcheck.warnings(m) if w["id"] == "module.empty"]
    assert [w["node"] for w in got] == ["svc:ghost"]


def test_ext_missing_accounted_for():
    m = copy.deepcopy(DEMO)
    m["nodes"].append({"id": "db:postgres:ORDERS_HOST", "kind": "datastore", "name": "ORDERS_HOST"})
    s = "- **env keys:** ORDERS_HOST; BILLING_URL; NOWHERE_TOKEN\n"
    got = [w["detail"].split()[2] for w in mapcheck.warnings(m, s) if w["id"] == "ext.missing"]
    assert got == ["NOWHERE_TOKEN"]


from examples_fixture import CONSUME, CREATE, cmap as small_map  # noqa: E402


def test_example_missing_lists_every_entry_point_without_one():
    m = small_map()
    m["examples"]["entries"] = [{"node": CONSUME, "key": "orders", "request": {}}]
    got = [w for w in mapcheck.warnings(m) if w["id"] == "example.missing"]
    assert got == [{"id": "example.missing", "node": CREATE,
                    "detail": f"entry point {CREATE} (POST /orders) has no example"}]


def test_a_method_with_several_keys_needs_an_example_per_key():
    m = small_map()
    m["files"]["m/api.py"]["routes"].append({"method": "GET", "path": "/orders/{id}", "handler": CREATE, "line": 5})
    m["examples"]["entries"] = [{"node": CREATE, "key": "POST /orders", "request": {}},
                                {"node": CONSUME, "key": "orders", "request": {}}]
    assert [w for w in mapcheck.warnings(m) if w["id"] == "example.missing"] == [
        {"id": "example.missing", "node": CREATE,
         "detail": f"entry point {CREATE} has no example for GET /orders/{{id}} (1 of 2 keys have one)"}]
    m["examples"]["entries"].append({"node": CREATE, "key": "GET /orders/{id}", "request": {}})
    assert [w for w in mapcheck.warnings(m) if w["id"] == "example.missing"] == []


def test_too_few_pins_are_listed_and_unpinned_ones_count():
    m = small_map()
    entries = len(examples.entry_points(m))
    m["pins"], m["unpinned"] = [], []
    got = [w["detail"] for w in mapcheck.warnings(m) if w["id"] == "pin.few"]
    want = min(3, entries)
    assert got == [f"0 pins (0 unpinned) for {entries} entry points: pin at least {want}"]
    m["unpinned"] = [f"gone-{i}" for i in range(want)]
    assert [w for w in mapcheck.warnings(m) if w["id"] == "pin.few"] == []


def test_pin_start_missing_is_listed_not_refused():
    m = small_map()
    m["pins"].append({"id": "gone", "title": "a gone start", "start": "m::m.api#old/0", "direction": "both",
                      "by": "user"})
    got = [w for w in mapcheck.warnings(m) if w["id"] == "pin.start-missing"]
    assert got == [{"id": "pin.start-missing", "node": None,
                    "detail": "pin gone (a gone start): start m::m.api#old/0 is not in this map"}]


def test_ext_missing_matches_a_service_by_its_words_and_clears_on_a_problem():
    m = {"nodes": [{"id": "svc:pricing", "kind": "service", "name": "pricing"},
                   {"id": "svc:billing", "kind": "service", "name": "billing"},
                   {"id": "3p:acmepay", "kind": "external", "name": "AcmePay EU"}],
         "relations": [],
         "problems": [{"text": "DOCKER_HOST is the Docker client's setting in a test helper, not an endpoint"}]}
    s = ("- **env keys:** PRICING_API_URL; PRICING_CALLBACK_URL; BILLING_SERVICE_URL; ACMEPAY_API_URL; DOCKER_HOST; "
         "PAYROLL_API_KEY\n")
    got = [w["detail"].split()[2] for w in mapcheck.warnings(m, s) if w["id"] == "ext.missing"]
    assert got == ["PAYROLL_API_KEY"]


def test_module_empty_skips_a_service_that_deploys_a_twin():
    m = copy.deepcopy(DEMO)
    m["nodes"].append({"id": "svc:sim", "kind": "service", "name": "sim", "twins": ["agent::agent/"]})
    assert [w for w in mapcheck.warnings(m) if w["id"] == "module.empty"] == []


def test_name_container_skips_a_constructor():
    m = {"nodes": [{"id": "svc:a", "kind": "service", "name": "a"},
                   {"id": "a::p", "kind": "package", "name": "p", "parent": "svc:a"},
                   {"id": "a::p.OrderController", "kind": "class", "name": "OrderController", "parent": "a::p"},
                   {"id": "a::p.OrderController#OrderController/2", "kind": "method", "name": "OrderController",
                    "parent": "a::p.OrderController"}], "relations": []}
    assert [w for w in mapcheck.warnings(m) if w["id"] == "name.container"] == []


def test_ext_missing_needs_every_word_of_the_key_to_name_one_owner():
    m = {"nodes": [{"id": "svc:payments-ui", "kind": "service", "name": "payments-ui"},
                   {"id": "svc:core", "kind": "service", "name": "core"}], "relations": []}
    s = "- **env keys:** PAYMENTS_UI_URL; CORE_API_URL; CORE_BANKING_URL; FRAUD_API_URL\n"
    got = [w["detail"].split()[2] for w in mapcheck.warnings(m, s) if w["id"] == "ext.missing"]
    assert got == ["CORE_BANKING_URL", "FRAUD_API_URL"]
