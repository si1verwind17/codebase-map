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


def test_data_two_way_call():
    m = {"nodes": [], "relations": [
        {"id": "r1", "kind": "ext-call", "from": "a", "to": "3p:x", "data": "both"},
        {"id": "r2", "kind": "request", "from": "a", "to": "b", "data": "forward"},
        {"id": "r3", "kind": "stream", "from": "a", "to": "b", "data": "both"}]}
    got = [(w["node"], w["detail"].split()[1]) for w in mapcheck.warnings(m) if w["id"] == "data.two-way-call"]
    assert got == [("a", "r1")]                  # a two-way stream is fine; a call's reply is no flow back


def test_external_unused():
    m = copy.deepcopy(DEMO)
    m["nodes"].append({"id": "3p:idle", "kind": "external", "name": "idle"})
    used = next(n["id"] for n in m["nodes"] if n["kind"] == "external" and n["id"] != "3p:idle")
    m["relations"] = [r for r in m["relations"] if used in (r["from"], r["to"])][:1]
    got = [w for w in mapcheck.warnings(m) if w["id"] == "external.unused"]
    assert sorted(w["node"] for w in got) == sorted(n["id"] for n in m["nodes"] if n["kind"] == "external"
                                                    and n["id"] != used)
    assert got[0]["detail"].startswith(f"external {got[0]['node']} has no relation")


def _routes_map(problems=()):
    nodes = [{"id": "f", "kind": "file", "name": "routes.js", "file": "src/routes.js", "line": 1},
             {"id": "f#setup/1", "kind": "method", "name": "setup", "parent": "f", "file": "src/routes.js",
              "line": 10, "metrics": {"loc": 10}},
             {"id": "f#show/1", "kind": "method", "name": "show", "parent": "f", "file": "src/routes.js",
              "line": 30, "metrics": {"loc": 3}}]
    routes = [{"method": "GET", "path": "/a", "handler": "f", "line": 3},
              {"method": "GET", "path": "/b", "handler": "f", "line": 4},
              {"method": "GET", "path": "/c", "handler": "f#setup/1", "line": 11},
              {"method": "GET", "path": "/d", "handler": "f#setup/1", "line": 12},
              {"method": "GET", "path": "/e", "handler": "f#show/1", "line": 13},
              {"method": "GET", "path": "/f", "handler": "f#show/1", "line": 30}]
    return {"nodes": nodes, "relations": [], "files": {"src/routes.js": {"node": "f", "routes": routes}},
            "problems": [{"text": t} for t in problems]}


def test_route_handlers_that_are_a_file_or_a_setup_function():
    got = [(w["id"], w["node"], w["detail"]) for w in mapcheck.warnings(_routes_map())
           if w["id"].startswith("route.")]
    assert got == [
        ("route.file-handler", "f", "2 routes in src/routes.js have the file as handler (GET /a at src/routes.js:3; "
         "GET /b at src/routes.js:4): no entry point, so no example or trace starts there. Point each at the "
         "function that handles it in stack.yaml (a handler group), or say in problems why the file is right"),
        ("route.setup-handler", "f#setup/1", "f#setup/1 registers 3 routes and is the handler of 2 of them (GET /c "
         "at src/routes.js:11; GET /d at src/routes.js:12): a function that sets routes up is rarely what handles "
         "them. Point each at its real handler in stack.yaml (a handler group), or say in problems why it is right")]
    quiet = _routes_map(["the inline handlers at src/routes.js:3 and f#setup/1 are what the code has"])
    assert [w for w in mapcheck.warnings(quiet) if w["id"].startswith("route.")] == []


def test_a_handler_in_another_file_is_no_setup_function():
    # a routes file whose routes point at methods of another file (Rails routes.rb to controller actions): the
    # method's lines are another file's, so routes on the same line numbers are not inside it
    nodes = [{"id": "r", "kind": "file", "name": "routes.rb", "file": "config/routes.rb", "line": 1},
             {"id": "c", "kind": "file", "name": "books_controller.rb", "file": "app/books_controller.rb", "line": 1},
             {"id": "c#index/0", "kind": "method", "name": "index", "parent": "c", "file": "app/books_controller.rb",
              "line": 2, "metrics": {"loc": 10}}]
    routes = [{"method": "GET", "path": f"/b{i}", "handler": "c#index/0", "line": 2 + i} for i in range(4)]
    cmap = {"nodes": nodes, "relations": [], "files": {"config/routes.rb": {"node": "r", "routes": routes}},
            "problems": []}
    assert [w for w in mapcheck.warnings(cmap) if w["id"].startswith("route.")] == []
