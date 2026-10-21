"""The map schema takes `fields`, `refs` and `returns_refs` (spec: traces §1.1, §1.2) and refuses bad shapes."""
import copy

from vizcode import mapcheck, structure
from vizcode.assemble import assemble

FILES = {"build.sbt": 'lazy val app = (project in file("."))\n',
         "src/main/scala/a/Api.scala": "package a\n\nfinal case class Quote(bay: String, total: Long)\n\n"
                                       "trait Api {\n  def price(q: Quote): Option[Quote]\n}\n"}


def test_scanned_map_with_fields_and_refs_is_valid(make_repo):
    cmap = assemble(structure.build(make_repo(FILES), "docs/viz-code"), {})
    by_id = {n["id"]: n for n in cmap["nodes"]}
    assert by_id[".::a.Quote"]["fields"] == [{"name": "bay", "type": "String", "visibility": "public"},
                                             {"name": "total", "type": "Long", "visibility": "public"}]
    sig = by_id[".::a.Api#price/1"]["signature"]
    assert sig["params"][0]["refs"] == [".::a.Quote"] and sig["returns_refs"] == [".::a.Quote"]
    assert mapcheck.check(cmap) == []


def test_schema_refuses_bad_fields_and_refs(make_repo):
    cmap = assemble(structure.build(make_repo(FILES), "docs/viz-code"), {})
    i = next(k for k, n in enumerate(cmap["nodes"]) if n["id"] == ".::a.Quote")
    j = next(k for k, n in enumerate(cmap["nodes"]) if n["id"] == ".::a.Api#price/1")
    for path, value in ((("fields",), []),                                   # an empty list: leave the key out
                        (("fields",), [{"name": "bay"}]),                    # type is required (null when none)
                        (("fields",), [{"name": "bay", "type": "S", "x": 1}]),
                        (("fields",), [{"name": "bay", "type": "S", "visibility": "internal"}]),
                        (("signature", "returns_refs"), []),
                        (("signature", "returns_refs"), [".::a.Quote", ".::a.Quote"])):
        bad = copy.deepcopy(cmap)
        node = bad["nodes"][i if path[0] == "fields" else j]
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
        assert any(e.startswith("schema: nodes/") for e in mapcheck.check(bad)), (path, value)
