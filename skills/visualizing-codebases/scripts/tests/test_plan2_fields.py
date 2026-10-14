"""The optional plan-2 facts on a map: schema types plus the where-they-may-appear rules."""
import copy

from meaning_fixture import MEANING

from vizcode import mapcheck, structure
from vizcode.assemble import assemble

EV = [{"file": "a.py", "line": 1}]


def base(shop_repo):
    """The shop map plus two topics (one a dead-letter topic), a bucket and a cache, all placed on the site floor."""
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    site = cmap["layout"]["containers"]["site"]["items"]
    row = max([p["row"] for p in site.values()] + [0]) + 1
    extra = [{"id": "topic:orders", "kind": "topic", "name": "orders", "delivery": "queue", "evidence": EV},
             {"id": "topic:orders-dlq", "kind": "topic", "name": "orders-dlq", "dead_letter_of": "topic:orders",
              "evidence": EV},
             {"id": "db:s3:UPLOADS", "kind": "datastore", "name": "uploads", "store": "bucket"},
             {"id": "db:redis:SOR", "kind": "datastore", "name": "sor", "store": "database", "evidence": EV}]
    for i, n in enumerate(extra):
        cmap["nodes"].append(n)
        site[n["id"]] = {"region": "main", "col": i, "row": row}
    for n in cmap["nodes"]:
        if n["id"] == "svc:worker":
            n["replicas"] = 3
    cmap["relations"] += [
        {"id": "r:event:svc:worker->topic:orders", "kind": "event", "from": "svc:worker", "to": "topic:orders",
         "key": "orders", "confidence": "confirmed", "evidence": EV},
        {"id": "r:event:topic:orders->svc:shop", "kind": "event", "from": "topic:orders", "to": "svc:shop",
         "key": "orders", "confidence": "confirmed", "evidence": EV, "subscription": "pull", "group": "billing"},
        {"id": "r:event:svc:shop->topic:orders-dlq", "kind": "event", "from": "svc:shop", "to": "topic:orders-dlq",
         "key": "orders-dlq", "confidence": "confirmed", "evidence": EV, "on_failure": True},
        {"id": "r:batch:svc:worker->svc:shop", "kind": "batch", "from": "svc:worker", "to": "svc:shop",
         "key": "nightly", "confidence": "confirmed", "evidence": EV, "job": "nightly-sync",
         "schedule": ["0 3 * * *", "0 0 3 * * *", "manual", "on orders-done"]},
    ]
    return cmap


def errors(cmap):
    return "\n".join(mapcheck.check(cmap))


def rel(cmap, rid):
    return next(r for r in cmap["relations"] if r["id"] == rid)


def node(cmap, nid):
    return next(n for n in cmap["nodes"] if n["id"] == nid)


def test_every_field_passes(shop_repo):
    assert mapcheck.check(base(shop_repo)) == []


def test_delivery_only_on_topic(shop_repo):
    cmap = base(shop_repo)
    node(cmap, "svc:shop")["delivery"] = "queue"
    assert "node svc:shop: delivery belongs on a topic node" in errors(cmap)


def test_replicas_only_on_service(shop_repo):
    cmap = base(shop_repo)
    node(cmap, "topic:orders")["replicas"] = 2
    assert "node topic:orders: replicas belongs on a service node" in errors(cmap)


def test_store_only_on_datastore(shop_repo):
    cmap = base(shop_repo)
    node(cmap, "svc:shop")["store"] = "cache"
    assert "node svc:shop: store belongs on a datastore node" in errors(cmap)


def test_dead_letter_of_only_on_topic(shop_repo):
    cmap = base(shop_repo)
    node(cmap, "svc:shop")["dead_letter_of"] = "topic:orders"
    assert "node svc:shop: dead_letter_of belongs on a topic node" in errors(cmap)


def test_dead_letter_of_missing_topic(shop_repo):
    cmap = base(shop_repo)
    node(cmap, "topic:orders-dlq")["dead_letter_of"] = "topic:gone"
    assert "node topic:orders-dlq: dead_letter_of topic:gone is not a topic" in errors(cmap)
    node(cmap, "topic:orders-dlq")["dead_letter_of"] = "svc:shop"
    assert "dead_letter_of svc:shop is not a topic" in errors(cmap)


def test_dead_letter_of_itself(shop_repo):
    cmap = base(shop_repo)
    node(cmap, "topic:orders-dlq")["dead_letter_of"] = "topic:orders-dlq"
    assert "node topic:orders-dlq: dead_letter_of names the topic itself" in errors(cmap)


def test_bad_enums_and_numbers_fail_the_schema(shop_repo):
    for patch in ({"delivery": "broadcast"}, {"replicas": 0}, {"store": "disk"}):
        cmap = base(shop_repo)
        target = {"delivery": "topic:orders", "replicas": "svc:worker", "store": "db:s3:UPLOADS"}[next(iter(patch))]
        node(cmap, target).update(patch)
        assert "schema:" in errors(cmap)


def test_on_failure_needs_a_topic_target(shop_repo):
    cmap = base(shop_repo)
    rel(cmap, "r:event:svc:shop->topic:orders-dlq")["on_failure"] = False
    assert mapcheck.check(cmap) == []
    r = rel(cmap, "r:event:topic:orders->svc:shop")
    r["on_failure"] = True
    assert "relation r:event:topic:orders->svc:shop: on_failure marks a publish to a topic" in errors(cmap)


def test_on_failure_only_on_event(shop_repo):
    cmap = base(shop_repo)
    rel(cmap, "r:batch:svc:worker->svc:shop")["on_failure"] = True
    assert "relation r:batch:svc:worker->svc:shop: on_failure belongs on an event relation" in errors(cmap)


def test_subscription_and_group_only_on_consume_side(shop_repo):
    cmap = base(shop_repo)
    r = rel(cmap, "r:event:svc:worker->topic:orders")
    r["subscription"] = "push"
    r["group"] = "g"
    out = errors(cmap)
    assert "relation r:event:svc:worker->topic:orders: subscription belongs on the consume side" in out
    assert "relation r:event:svc:worker->topic:orders: group belongs on the consume side" in out


def test_subscription_group_only_on_event(shop_repo):
    cmap = base(shop_repo)
    r = rel(cmap, "r:batch:svc:worker->svc:shop")
    r["subscription"] = "push"
    r["group"] = "g"
    out = errors(cmap)
    assert "subscription belongs on an event relation" in out and "group belongs on an event relation" in out


def test_schedule_and_job_only_on_batch(shop_repo):
    cmap = base(shop_repo)
    r = rel(cmap, "r:event:svc:worker->topic:orders")
    r["schedule"] = ["manual"]
    r["job"] = "x"
    out = errors(cmap)
    assert "relation r:event:svc:worker->topic:orders: schedule belongs on a batch relation" in out
    assert "relation r:event:svc:worker->topic:orders: job belongs on a batch relation" in out


def test_bad_cron_string(shop_repo):
    cmap = base(shop_repo)
    rel(cmap, "r:batch:svc:worker->svc:shop")["schedule"] = ["every day", "on "]
    out = errors(cmap)
    assert 'schedule entry "every day" is not a 5- or 6-field cron expression, "manual" or "on <event>"' in out
    assert 'schedule entry "on " is not' in out


def test_empty_schedule_group_job_fail_the_schema(shop_repo):
    for patch in ({"schedule": []}, {"job": ""}):
        cmap = base(shop_repo)
        rel(cmap, "r:batch:svc:worker->svc:shop").update(patch)
        assert "schema:" in errors(cmap)
    cmap = base(shop_repo)
    rel(cmap, "r:event:topic:orders->svc:shop")["group"] = ""
    assert "schema:" in errors(cmap)
    rel(cmap, "r:event:topic:orders->svc:shop").update(group="g", subscription="lazy")
    assert "schema:" in errors(cmap)


def test_store_defaults_from_engine_and_keeps_override(shop_repo):
    meaning = copy.deepcopy(MEANING)
    engines = {"redis": "cache", "Memcached": "cache", "valkey": "cache", "keydb": "cache", "s3": "bucket",
               "gcs": "bucket", "blob": "bucket", "minio": "bucket", "r2": "bucket", "bigquery": "warehouse",
               "SNOWFLAKE": "warehouse", "redshift": "warehouse", "clickhouse": "warehouse",
               "databricks": "warehouse", "mysql": "database"}
    for e in engines:
        meaning["nodes"].append({"id": f"db:{e}:K", "kind": "datastore", "name": e})
    meaning["nodes"].append({"id": "db:redis:KEPT", "kind": "datastore", "name": "kept", "store": "database"})
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), meaning)
    got = {n["id"]: n.get("store") for n in cmap["nodes"] if n["kind"] == "datastore"}
    for e, want in engines.items():
        assert got[f"db:{e}:K"] == want
    assert got["db:postgres:DB_HOST"] == "database"
    assert got["db:redis:KEPT"] == "database"


def test_topic_delivery_and_dead_letter_need_evidence(shop_repo):
    for field in ("delivery", "dead_letter_of"):
        cmap = base(shop_repo)
        t = node(cmap, "topic:orders-dlq")
        t.pop("evidence")
        t.setdefault(field, "queue" if field == "delivery" else "topic:orders")
        assert "node topic:orders-dlq: " in errors(cmap) and "needs evidence" in errors(cmap)


def test_replicas_need_evidence(shop_repo):
    cmap = base(shop_repo)
    node(cmap, "svc:worker").pop("evidence")
    assert "node svc:worker" in errors(cmap) and "needs evidence" in errors(cmap)


def test_store_override_needs_evidence_default_does_not(shop_repo):
    cmap = base(shop_repo)
    assert "db:s3:UPLOADS" not in errors(cmap)                 # bucket is the s3 default
    node(cmap, "db:redis:SOR").pop("evidence")                 # database is not the redis default
    assert "node db:redis:SOR: store needs evidence" in errors(cmap)


def test_stale_node_refused(shop_repo):
    cmap = base(shop_repo)
    node(cmap, "topic:orders")["stale"] = True
    assert "node topic:orders: stale" in errors(cmap)


def test_cron_fields_are_checked_not_just_counted(shop_repo):
    for good in ("*/15 * * * *", "0 2 * * MON-FRI", "0 0 3 * * *", "0 9 ? * 1#2", "0 0 L * *", "30 6 * JAN,JUL *"):
        assert not mapcheck._bad_schedule_entry(good), good
    for bad in ("every day at 2 am", "run it nightly please", "daily", "@daily", "* * *", "a b c d e", "0 2 * * * * *"):
        assert mapcheck._bad_schedule_entry(bad), bad
    cmap = base(shop_repo)
    rel(cmap, "r:batch:svc:worker->svc:shop")["schedule"] = ["every day at 2 am"]
    assert "not a 5- or 6-field cron" in errors(cmap)
