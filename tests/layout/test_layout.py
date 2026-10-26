import copy
import json

import assemble as assemble_cli
import extract
from conftest import commit_all, write_files
from meaning_fixture import MEANING

from vizcode.map import mapcheck
from vizcode.scan import structure
from vizcode.map.assemble import assemble
from vizcode.layout.layout import layered, site


def built(repo, meaning=MEANING, previous=None):
    return assemble(structure.build(repo, "docs/viz-code"), copy.deepcopy(meaning), previous)


def test_layered_is_deterministic_and_breaks_cycles():
    edges = [("a", "b"), ("b", "c"), ("c", "a"), ("a", "d")]
    first = layered(["d", "c", "b", "a"], edges)
    assert first == layered(["a", "b", "c", "d"], list(reversed(edges)))
    assert first["a"][0] == 0 and first["b"][0] == 1 and first["c"][0] == 2


def synthetic(services, externals=(), rels=(), stores=("db:pg:DB",), libs=()):
    nodes = [{"id": s, "kind": "service", "name": s} for s in services] + \
            [{"id": x, "kind": "external", "name": x} for x in externals] + \
            [{"id": d, "kind": "datastore", "name": d} for d in stores] + \
            [{"id": l, "kind": "library", "name": l} for l in libs]
    relations = [{"kind": k, "from": a, "to": b, "data": d} for a, b, k, d in rels]
    return {"nodes": nodes, "relations": relations}


MAIN_BUS = synthetic(
    ["svc:market", "svc:agent", "svc:order", "svc:backfill", "svc:dash", "svc:dash-api"],
    ["3p:ws", "3p:rest", "3p:chat"],
    [("svc:market", "3p:ws", "stream", "back"), ("svc:market", "svc:agent", "request", "both"),
     ("svc:agent", "svc:order", "request", "both"), ("svc:order", "3p:rest", "ext-call", "forward"),
     ("svc:backfill", "3p:rest", "ext-call", "forward"), ("svc:backfill", "db:pg:DB", "db-write", "forward"),
     ("svc:market", "db:pg:DB", "db-write", "forward"), ("svc:dash-api", "db:pg:DB", "db-read", "back"),
     ("svc:dash", "svc:dash-api", "request", "both"),
     ("svc:market", "3p:chat", "ext-call", "forward"), ("svc:agent", "3p:chat", "ext-call", "forward"),
     ("svc:order", "3p:chat", "ext-call", "forward")])


def test_main_bus_regions():
    floor = site(MAIN_BUS, None)
    it = floor["items"]
    assert floor["strategy"] == "main-bus" and floor["utilities"] == ["3p:chat"]
    assert it["3p:ws"]["col"] == 0 and it["svc:market"]["col"] == 1                    # source yard, then line
    assert it["svc:agent"]["col"] == 2 and it["svc:order"]["col"] == 3
    assert it["3p:rest"]["col"] == max(p["col"] for p in it.values() if p["region"] == "line")
    assert {it["svc:dash"]["region"], it["svc:dash-api"]["region"]} == {"bay"}
    assert it["db:pg:DB"]["region"] == "bus" and floor["lanes"] == [{"id": "db:pg:DB", "row": 0}]
    assert "3p:chat" not in it


def test_sticky_positions_survive_a_new_service():
    before = site(MAIN_BUS, None)
    grown = copy.deepcopy(MAIN_BUS)
    grown["nodes"].append({"id": "svc:risk", "kind": "service", "name": "svc:risk"})
    grown["relations"].append({"kind": "request", "from": "svc:order", "to": "svc:risk", "data": "both"})
    after = site(grown, before)
    for k, p in before["items"].items():
        assert after["items"][k] == p, k
    cells = [(p["region"], p["col"], p["row"]) for p in after["items"].values()]
    assert len(cells) == len(set(cells))                                                # no overlap


def test_removed_service_leaves_others_in_place():
    before = site(MAIN_BUS, None)
    shrunk = copy.deepcopy(MAIN_BUS)
    shrunk["nodes"] = [n for n in shrunk["nodes"] if n["id"] != "svc:backfill"]
    shrunk["relations"] = [r for r in shrunk["relations"] if "svc:backfill" not in (r["from"], r["to"])]
    after = site(shrunk, before)
    assert "svc:backfill" not in after["items"]
    for k, p in after["items"].items():
        assert before["items"][k] == p, k


def test_city_grid_above_twenty_services():
    svcs = [f"svc:s{i:02d}" for i in range(40)]
    rels = [(svcs[i], svcs[i + 1], "request", "both") for i in range(39)] + \
           [(s, "db:pg:DB", "db-write", "forward") for s in svcs[::5]]
    floor = site(synthetic(svcs, rels=rels), None)
    it = floor["items"]
    assert floor["strategy"] == "city-grid"
    cells = [(p["col"], p["row"]) for p in it.values() if p["region"] == "grid"]
    assert len(cells) == len(set(cells)) == 41
    dist = [abs(it[a]["col"] - it[b]["col"]) + abs(it[a]["row"] - it[b]["row"]) for a, b, *_ in rels[:39]]
    assert sum(dist) / len(dist) <= 2.0                                                  # neighbours stay close
    again = site(synthetic(svcs, rels=rels), floor)
    assert again["items"] == it


def test_inner_floors_and_groups_validate(shop_repo):
    cmap = built(shop_repo)
    c = cmap["layout"]["containers"]
    shop_floor = c["svc:shop"]
    assert shop_floor["strategy"] == "bands"
    assert shop_floor["items"]["shop::io.demo.shop.api/"] == {"region": "line", "col": 0, "row": 0}
    assert shop_floor["items"]["shop::io.demo.shop.repo/"]["region"] == "bus"
    assert c["db:postgres:DB_HOST"]["strategy"] == "shelves"
    assert c["worker::worker.main.Job"]["strategy"] == "layered"
    assert mapcheck.check(cmap) == []


def test_crowded_package_gets_groups_and_group_floors(make_repo):
    files = {"pkg/__init__.py": ""}
    for i in range(1, 31):
        files[f"pkg/strat{i}.py"] = f"class Exposure{i}:\n    def a(self):\n        pass\n\n    def b(self):\n        pass\n"
    repo = make_repo(files)
    cmap = assemble(structure.build(repo, "docs/viz-code"),
                    {"nodes": [{"id": "svc:pkg", "kind": "service", "name": "pkg", "modules": ["pkg"], "evidence": [{"file": "pkg/__init__.py", "line": 1}]}]})
    floor = cmap["layout"]["containers"]["pkg::pkg/"]
    assert len(floor["items"]) <= 24 and floor["groups"]
    for g in floor["groups"]:
        assert g["id"] in floor["items"] and g["id"] in cmap["layout"]["containers"]
    assert mapcheck.check(cmap) == []


def test_assemble_cli_keeps_positions_and_relayout_resets(shop_repo):
    out = shop_repo / "docs" / "viz-code"
    extract.main([str(shop_repo)])
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    first = json.loads((out / "code-map.json").read_text())["layout"]["containers"]
    commit_all(shop_repo, "map")
    write_files(shop_repo, {"worker/extra.py": "def zz():\n    pass\n", "aaa/__init__.py": "", "aaa/x.py": "def f():\n    pass\n"})
    commit_all(shop_repo, "grow")
    extract.main([str(shop_repo)])
    assert assemble_cli.main([str(shop_repo)]) == 0
    second = json.loads((out / "code-map.json").read_text())["layout"]["containers"]
    for cid, floor in first.items():
        for iid, p in floor["items"].items():
            assert second[cid]["items"][iid] == p, (cid, iid)
    assert "lib:aaa" in second["site"]["items"]
    assert assemble_cli.main([str(shop_repo), "--relayout"]) == 0


def test_a_tall_layer_wraps_into_extra_columns():
    from vizcode.layout.layout import MAX_ROWS, wrap_columns
    lay = {f"m{i:02d}": (0, i) for i in range(20)} | {"tail": (1, 0)}
    cells = wrap_columns(lay)
    assert max(r for _, r in cells.values()) < MAX_ROWS
    assert len(set(cells.values())) == len(cells)                     # no two items share a cell
    assert cells["tail"][0] > max(c for k, (c, _) in cells.items() if k != "tail")   # later layers move right
