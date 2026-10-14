"""The field guide's tiny example maps: each is valid, holds its pattern, and is committed as generated."""
import json
import re

import pytest

import guide_maps
from vizcode import mapcheck

NAMES = list(guide_maps.EXAMPLES)


@pytest.fixture(scope="module")
def maps():
    return {name: guide_maps.build(name) for name in NAMES}


def kinds(cmap, what):
    return {x["kind"] for x in cmap[what]}


def by_id(cmap):
    return {n["id"]: n for n in cmap["nodes"]}


def rels(cmap, kind):
    return [r for r in cmap["relations"] if r["kind"] == kind]


def test_the_guide_lists_fifteen_examples():
    assert NAMES == ["floors", "codes", "belt", "splitters", "pipe", "drones", "queues", "push_pull", "rail",
                     "storage", "outside", "shared", "crossings", "layers", "trace"]


@pytest.mark.parametrize("name", NAMES)
def test_every_example_passes_mapcheck(maps, name):
    assert mapcheck.check(maps[name]) == []
    assert maps[name]["problems"] == [], "a guide example should carry no problems"


def test_the_generator_is_deterministic(maps):
    for name in NAMES:
        assert guide_maps.text(guide_maps.build(name)) == guide_maps.text(maps[name])


@pytest.mark.parametrize("name", NAMES)
def test_committed_maps_match_the_generator(maps, name):
    path = guide_maps.OUT / f"{name}.code-map.json"
    assert path.read_text() == guide_maps.text(maps[name]), "run scripts/guide_maps.py and commit its output"


def test_floors_has_two_services_one_with_a_few_packages(maps):
    m = maps["floors"]
    services = [n for n in m["nodes"] if n["kind"] == "service"]
    assert len(services) == 2
    floor = m["layout"]["containers"]["svc:orders"]["items"]
    assert sum(by_id(m)[i]["kind"] == "package" for i in floor) >= 3
    (req,) = rels(m, "request")
    assert req["from"].startswith("orders::") and req["to"].startswith("billing::") and req["data"] == "forward"
    assert rels(m, "calls")


def test_codes_has_every_code_level(maps):
    assert {"service", "package", "file", "class", "method"} <= kinds(maps["codes"], "nodes")
    assert len([n for n in maps["codes"]["nodes"] if n["kind"] == "service"]) == 1


def test_belt_has_a_one_way_and_a_two_way_request(maps):
    assert sorted(r["data"] for r in rels(maps["belt"], "request")) == ["both", "forward"]
    assert kinds(maps["belt"], "relations") == {"request"}


def test_splitters_fan_out_from_one_caller_and_in_to_one_callee(maps):
    req = rels(maps["splitters"], "request")
    out = [r for r in req if r["from"].startswith("orders::")]
    into = [r for r in req if r["to"].startswith("reports::")]
    assert len({r["to"] for r in out}) == 3 and len({r["from"] for r in into}) == 3


def test_pipe_is_one_stream(maps):
    assert [r["kind"] for r in maps["pipe"]["relations"]] == ["stream"]
    assert len([n for n in maps["pipe"]["nodes"] if n["kind"] == "service"]) == 2


def test_drones_one_producer_one_topic_two_consumers(maps):
    m = maps["drones"]
    topics = [n for n in m["nodes"] if n["kind"] == "topic"]
    assert len(topics) == 1 and topics[0].get("delivery") == "fan-out"
    ev = rels(m, "event")
    assert len([r for r in ev if r["to"] == topics[0]["id"]]) == 1
    assert len([r for r in ev if r["from"] == topics[0]["id"]]) == 2


def test_queues_has_a_work_queue_two_workers_and_a_dead_letter_topic(maps):
    m = maps["queues"]
    nodes = by_id(m)
    queue = next(n for n in nodes.values() if n["kind"] == "topic" and not n.get("dead_letter_of"))
    dead = next(n for n in nodes.values() if n.get("dead_letter_of") == queue["id"])
    assert queue["delivery"] == "queue"
    assert len([r for r in rels(m, "event") if r["from"] == queue["id"]]) == 2
    assert any(r.get("on_failure") and r["to"] == dead["id"] for r in rels(m, "event"))


def test_push_pull_has_both_subscriptions_and_a_consumer_with_replicas(maps):
    m = maps["push_pull"]
    subs = {r["subscription"]: r for r in rels(m, "event") if "subscription" in r}
    assert set(subs) == {"push", "pull"}
    assert any(n.get("replicas", 1) > 1 for n in m["nodes"] if n["kind"] == "service")


def test_rail_is_a_scheduled_batch_into_another_service(maps):
    (b,) = rels(maps["rail"], "batch")
    assert b["schedule"] and b["job"] and b["from"] == "svc:jobs" and b["to"].startswith("billing::")


def test_storage_has_a_database_read_and_written_a_sole_cache_and_a_bucket(maps):
    m = maps["storage"]
    stores = {n["store"]: n["id"] for n in m["nodes"] if n["kind"] == "datastore"}
    assert set(stores) == {"database", "cache", "bucket"}
    touches = lambda kind, store: [r for r in rels(m, kind) if r["to"].startswith(stores[store])]  # noqa: E731
    assert touches("db-read", "database") and touches("db-write", "database")
    assert touches("db-write", "bucket")
    assert {r["from"].split("::")[0] for k in ("db-read", "db-write") for r in touches(k, "cache")} == {"orders"}


def test_outside_has_an_outside_call_a_webhook_and_a_utility(maps):
    m = maps["outside"]
    nodes = by_id(m)
    assert any(nodes[r["from"]]["kind"] == "external" for r in rels(m, "request"))
    assert m["layout"]["containers"]["site"]["utilities"] == ["3p:mail"]
    called = {r["to"] for r in rels(m, "ext-call")} - {"3p:mail"}
    assert called and all(nodes[x]["kind"] == "external" for x in called)


def test_shared_has_a_library_one_service_uses_and_an_implements_pair(maps):
    m = maps["shared"]
    assert [r["to"] for r in rels(m, "uses-code")] == ["lib:common"]
    assert m["layout"]["containers"]["site"]["items"]["lib:common"]["region"] == "shelf"
    assert any(r["to"].startswith("common::") for r in rels(m, "calls"))
    impl = [n for n in m["nodes"] if n.get("implements")]
    assert len(impl) == 1 and by_id(m)[impl[0]["implements"][0]]["kind"] == "class"


def test_crossings_has_an_inferred_line(maps):
    req = rels(maps["crossings"], "request")
    assert len(req) == 4 and [r["confidence"] for r in req].count("inferred") == 1


def test_layers_has_one_item_used_by_eight(maps):
    floor = maps["layers"]["layout"]["containers"]["svc:orders"]
    assert floor["hubs"] == ["orders::audit/"]
    callers = {r["from"].split(".")[0] for r in rels(maps["layers"], "calls") if r["to"].startswith("orders::audit.")}
    assert len(callers) == 8


def test_trace_has_a_pin_examples_and_a_library_call(maps):
    m = maps["trace"]
    (pin,) = m["pins"]
    assert pin["direction"] == "both" and pin["start"].endswith("#create_invoice/1")
    assert len(m["examples"]["entries"]) == 3 and len(m["examples"]["types"]) == 2
    assert all(e.get("fingerprint") for e in m["examples"]["entries"])
    ids = {n["id"]: n for n in m["nodes"]}
    assert any(n.get("fields") for n in ids.values() if n["kind"] == "class")
    callees = {r["to"] for r in m["relations"] if r["kind"] == "calls"}
    assert any(c.startswith("common::") for c in callees)


PRODUCTS = re.compile(r"\b(airflow|flyte|kafka|rabbitmq|sqs|pub/?sub|celery|stripe|postgres(ql)?|redis|s3|bigquery)\b",
                      re.IGNORECASE)


def test_no_product_names_anywhere(maps):
    for name, m in maps.items():
        assert not PRODUCTS.findall(json.dumps(m)), name


def test_guide_maps_carry_no_stack_stamp():
    for name in guide_maps.EXAMPLES:
        assert "stack" not in guide_maps.build(name)["meta"]
