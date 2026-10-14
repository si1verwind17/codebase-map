"""Type and entry fingerprints (spec: traces §1.4)."""
import copy
import re

from vizcode import structure
from vizcode.fingerprint import entry_fingerprint, type_fingerprint

QUOTE = {"id": "svc::a.Quote", "kind": "class", "name": "Quote",
         "fields": [{"name": "bay", "type": "BayId"}, {"name": "total", "type": "Long"}]}
BAY = {"id": "svc::a.BayId", "kind": "class", "name": "BayId", "fields": [{"name": "value", "type": "String"}]}
PRICE = {"id": "svc::a.Api#price/2", "kind": "method", "name": "price",
         "signature": {"params": [{"name": "bay", "type": "BayId", "refs": ["svc::a.BayId"]},
                                  {"name": "n", "type": "Int"}],
                       "returns": "Task[Quote]", "returns_refs": ["svc::a.Quote"]}}
NODES = {n["id"]: n for n in (QUOTE, BAY, PRICE)}


def test_type_fingerprint_is_short_hex_and_stable():
    fp = type_fingerprint(QUOTE)
    assert re.fullmatch(r"[0-9a-f]{12}", fp)
    assert type_fingerprint(copy.deepcopy(QUOTE)) == fp
    # other node keys never count: only the fields
    assert type_fingerprint({**QUOTE, "line": 99, "summary": "x", "id": "other::b.Quote"}) == fp


def test_type_fingerprint_changes_with_a_field_name_type_or_order():
    fp = type_fingerprint(QUOTE)
    renamed = {**QUOTE, "fields": [{"name": "bayId", "type": "BayId"}, QUOTE["fields"][1]]}
    retyped = {**QUOTE, "fields": [QUOTE["fields"][0], {"name": "total", "type": "BigDecimal"}]}
    reordered = {**QUOTE, "fields": list(reversed(QUOTE["fields"]))}
    added = {**QUOTE, "fields": QUOTE["fields"] + [{"name": "note", "type": None}]}
    assert len({fp, *(type_fingerprint(x) for x in (renamed, retyped, reordered, added))}) == 5


def test_type_fingerprint_of_a_class_without_fields():
    assert type_fingerprint({"id": "x", "kind": "class", "name": "X"}) == type_fingerprint({"fields": []})


def test_entry_fingerprint_follows_signature_and_referenced_types_one_level():
    fp = entry_fingerprint(PRICE, NODES)
    assert re.fullmatch(r"[0-9a-f]{12}", fp)
    assert entry_fingerprint(copy.deepcopy(PRICE), copy.deepcopy(NODES)) == fp
    renamed_param = copy.deepcopy(PRICE)
    renamed_param["signature"]["params"][1]["name"] = "count"
    new_return = copy.deepcopy(PRICE)
    new_return["signature"]["returns"] = "Task[Option[Quote]]"
    quote_changed = {**NODES, QUOTE["id"]: {**QUOTE, "fields": QUOTE["fields"][:1]}}
    assert entry_fingerprint(renamed_param, NODES) != fp
    assert entry_fingerprint(new_return, NODES) != fp
    assert entry_fingerprint(PRICE, quote_changed) != fp
    # one level: a change in a class that a referenced class's field names does not count
    bay_field_class = {"id": "svc::a.String", "kind": "class", "name": "String", "fields": [{"name": "x", "type": "Int"}]}
    assert entry_fingerprint(PRICE, {**NODES, bay_field_class["id"]: bay_field_class}) == fp


def test_entry_fingerprint_without_signature_or_with_a_missing_ref():
    bare = {"id": "svc::a.Api#ping/0", "kind": "method", "name": "ping"}
    assert re.fullmatch(r"[0-9a-f]{12}", entry_fingerprint(bare, {}))
    assert entry_fingerprint(PRICE, {}) != entry_fingerprint(PRICE, NODES)     # refs read as null, no crash


def test_fingerprints_from_a_scan_are_stable_across_rescans(make_repo):
    files = {"build.sbt": 'lazy val app = (project in file("."))\n',
             "src/main/scala/a/Api.scala":
                 "package a\n\nfinal case class Quote(bay: String, total: Long)\n\n"
                 "trait Api {\n  def price(bay: String): Option[Quote]\n}\n"}
    s1 = structure.build(make_repo(files, name="one"), "docs/viz-code")
    s2 = structure.build(make_repo(files, name="two"), "docs/viz-code")
    fps = []
    for s in (s1, s2):
        by_id = {n["id"]: n for n in s["nodes"]}
        fps.append((type_fingerprint(by_id[".::a.Quote"]), entry_fingerprint(by_id[".::a.Api#price/1"], by_id)))
    assert fps[0] == fps[1]
    changed = {**files, "src/main/scala/a/Api.scala": files["src/main/scala/a/Api.scala"].replace("total: Long",
                                                                                                    "total: BigDecimal")}
    s3 = structure.build(make_repo(changed, name="three"), "docs/viz-code")
    by_id = {n["id"]: n for n in s3["nodes"]}
    assert type_fingerprint(by_id[".::a.Quote"]) != fps[0][0]
    assert entry_fingerprint(by_id[".::a.Api#price/1"], by_id) != fps[0][1]
