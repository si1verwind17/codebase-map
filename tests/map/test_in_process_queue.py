"""In-process queues: a service's own queue or hub, joined to its producers and consumers by `hand-off`."""
import copy

import pytest
from meaning_fixture import MEANING

from vizcode.map import mapcheck
from vizcode.scan import structure
from vizcode.map.assemble import assemble

EV = [{"file": "worker/main.py", "line": 1}]
Q = "inq:worker:jobs"
PRODUCER = "worker::worker.main#run/2"
CONSUMER = "worker::worker.util.helpers#fmt/1"


def meaning(**queue):
    m = copy.deepcopy(MEANING)
    m["nodes"].append({"id": Q, "kind": "in-process-queue", "parent": "svc:worker", "name": "jobs",
                       "delivery": "queue", "evidence": EV, **queue})
    m["relations"] += [
        {"kind": "hand-off", "from": PRODUCER, "to": Q, "confidence": "confirmed", "evidence": EV},
        {"kind": "hand-off", "from": Q, "to": CONSUMER, "confidence": "confirmed", "evidence": EV}]
    return m


def build(shop_repo, m):
    return assemble(structure.build(shop_repo, "docs/viz-code"), m)


def errors(cmap):
    return "\n".join(mapcheck.check(cmap))


def test_queue_and_hand_offs_pass_and_default_forward(shop_repo):
    cmap = build(shop_repo, meaning())
    assert mapcheck.check(cmap) == []
    offs = [r for r in cmap["relations"] if r["kind"] == "hand-off"]
    assert len(offs) == 2 and all(r["data"] == "forward" for r in offs)


def test_queue_sits_on_its_service_floor_never_on_the_site(shop_repo):
    floors = build(shop_repo, meaning())["layout"]["containers"]
    assert Q not in floors["site"]["items"]
    assert floors["svc:worker"]["items"][Q] == {"region": "airfield", "col": 0, "row": 0}


@pytest.mark.parametrize("parent", ["lib:common", None])
def test_queue_parent_must_be_a_service(shop_repo, parent):
    cmap = build(shop_repo, meaning())
    next(n for n in cmap["nodes"] if n["id"] == Q)["parent"] = parent
    assert f"node {Q}: in-process-queue cannot sit under" in errors(cmap)


@pytest.mark.parametrize("field", ["delivery", "evidence"])
def test_queue_needs_delivery_and_evidence(shop_repo, field):
    cmap = build(shop_repo, meaning())
    next(n for n in cmap["nodes"] if n["id"] == Q).pop(field)
    assert f"node {Q}: in-process-queue needs {field}" in errors(cmap)


def test_hand_off_must_join_a_queue_to_a_method_of_its_service(shop_repo):
    m = meaning()
    m["relations"].append({"kind": "hand-off", "from": "shop::io.demo.shop.api.OrderApi$#getEndpoint/0", "to": Q,
                           "confidence": "confirmed", "evidence": EV})
    m["relations"].append({"kind": "hand-off", "from": PRODUCER, "to": CONSUMER,
                           "confidence": "confirmed", "evidence": EV})
    text = errors(build(shop_repo, m))
    assert "getEndpoint/0" in text and "not in svc:worker" in text
    assert f"{PRODUCER}->{CONSUMER}" in text and "must start or end at an in-process-queue" in text


def test_a_pin_can_start_at_a_queue(shop_repo):
    m = meaning()
    m["pins"] = [{"id": "jobs", "title": "jobs", "start": Q, "direction": "downstream", "by": "agent"}]
    assert mapcheck.check(build(shop_repo, m)) == []
