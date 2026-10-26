"""Regression tests for the Part A final review: crowded services, many families, group floors,
topic lanes, event chains, the read-only bay, layout invariants and city-grid stickiness."""
import copy

import pytest

from test_layout import MAIN_BUS, synthetic

from vizcode.map import mapcheck
from vizcode.scan import structure
from vizcode.map.assemble import assemble
from vizcode.layout.layout import site
from vizcode.map.roles import GROUP_THRESHOLD, group_children


def test_service_with_thirty_packages_assembles(make_repo):
    files = {}
    for i in range(30):
        files[f"big/p{i:02d}/__init__.py"] = ""
        files[f"big/p{i:02d}/m.py"] = f"def f{i}():\n    pass\n"
    files["big/__init__.py"] = ""
    repo = make_repo(files)
    cmap = assemble(structure.build(repo, "docs/viz-code"),
                    {"nodes": [{"id": "svc:big", "kind": "service", "name": "big", "modules": ["big"], "evidence": [{"file": "big/__init__.py", "line": 1}]}]})
    assert mapcheck.check(cmap) == []
    assert len(cmap["layout"]["containers"]["svc:big"]["items"]) <= GROUP_THRESHOLD


def test_many_families_never_crash_and_fit():
    names = [f"Fam{chr(65 + i // 3)}{chr(65 + (i // 3) % 26)}{i % 3}" for i in range(75)] + ["Loner"]
    by_id = {f"c{i}": {"id": f"c{i}", "kind": "class", "name": n} for i, n in enumerate(names)}
    items, groups = group_children("pkg", sorted(by_id), by_id, {k: 3 for k in by_id})
    assert len(items) <= GROUP_THRESHOLD
    placed = [i for i in items if not i.startswith("grp:")] + [m for g in groups for m in g["members"]]
    assert sorted(placed) == sorted(by_id)
    assert len({g["id"] for g in groups}) == len(groups)


@pytest.mark.parametrize("loose", [0, 1, 2])
def test_twins_filling_the_floor_never_crash(loose):
    twins = [f"twin:m{i:03d}" for i in range(GROUP_THRESHOLD + 5)]
    by_id = {f"c{i}": {"id": f"c{i}", "kind": "class", "name": f"C{i}"} for i in range(loose)}
    items, groups = group_children("pkg", twins + sorted(by_id), by_id, {k: 3 for k in by_id})
    placed = [i for i in items if not i.startswith("grp:")] + [m for g in groups for m in g["members"]]
    assert sorted(placed) == sorted(twins + list(by_id))


def test_data_group_id_never_collides_with_a_family():
    by_id = {f"c{i}": {"id": f"c{i}", "kind": "file", "name": n} for i, n in enumerate(
        [f"data{k}.py" for k in range(1, 4)] + [f"x{k}.py" for k in range(30)])}
    methods = {k: (0 if v["name"].startswith("x") else 2) for k, v in by_id.items()}
    _, groups = group_children("pkg", sorted(by_id), by_id, methods)
    assert len({g["id"] for g in groups}) == len(groups)


def test_group_floors_are_condensed_and_keep_edges(make_repo):
    files = {"pkg/__init__.py": ""}
    for i in range(1, 61):
        nxt = f"Exposure{i + 1}().run()\n" if i < 60 else "pass\n"
        files[f"pkg/s{i:02d}.py"] = (f"from pkg.s{i + 1 if i < 60 else i:02d} import *\n\n\nclass Exposure{i}:\n"
                                     f"    def run(self):\n        {nxt}\n    def b(self):\n        pass\n")
    repo = make_repo(files)
    cmap = assemble(structure.build(repo, "docs/viz-code"),
                    {"nodes": [{"id": "svc:pkg", "kind": "service", "name": "pkg", "modules": ["pkg"], "evidence": [{"file": "pkg/__init__.py", "line": 1}]}]})
    floors = cmap["layout"]["containers"]
    assert max(len(f["items"]) for f in floors.values()) <= GROUP_THRESHOLD
    assert mapcheck.check(cmap) == []


def test_two_topics_on_one_broker_stay_on_its_lane():
    m = synthetic(["svc:a", "svc:b"], stores=("db:pg:DB",))
    m["nodes"] += [{"id": "topic:kafka:t1", "kind": "topic", "name": "t1"},
                   {"id": "topic:kafka:t2", "kind": "topic", "name": "t2"}]
    m["relations"] += [{"kind": "event", "from": "svc:a", "to": t, "data": "forward"} for t in ("topic:kafka:t1", "topic:kafka:t2")]
    m["relations"] += [{"kind": "db-write", "from": "svc:a", "to": "db:pg:DB", "data": "forward"},
                       {"kind": "db-write", "from": "svc:b", "to": "db:pg:DB", "data": "forward"}]
    floor = site(m, None)
    lane = {l["id"]: l["row"] for l in floor["lanes"]}
    for t in ("topic:kafka:t1", "topic:kafka:t2"):
        assert floor["items"][t]["row"] == lane["broker:kafka"], t


def test_event_chain_becomes_a_line():
    m = synthetic(["svc:a", "svc:b", "svc:c"], stores=())
    m["nodes"] += [{"id": "topic:k:t1", "kind": "topic", "name": "t1"}, {"id": "topic:k:t2", "kind": "topic", "name": "t2"}]
    m["relations"] += [{"kind": "event", "from": "svc:a", "to": "topic:k:t1", "data": "forward"},
                       {"kind": "event", "from": "topic:k:t1", "to": "svc:b", "data": "forward"},
                       {"kind": "event", "from": "svc:b", "to": "topic:k:t2", "data": "forward"},
                       {"kind": "event", "from": "topic:k:t2", "to": "svc:c", "data": "forward"}]
    it = site(m, None)["items"]
    assert (it["svc:a"]["col"], it["svc:b"]["col"], it["svc:c"]["col"]) == (0, 1, 2)


def test_called_leaf_service_stays_on_the_line():
    m = synthetic(["svc:a", "svc:b", "svc:pricing"],
                  rels=[("svc:a", "svc:b", "request", "both"), ("svc:b", "svc:pricing", "request", "both")])
    it = site(m, None)["items"]
    assert {it[s]["region"] for s in ("svc:a", "svc:b", "svc:pricing")} == {"line"}


def test_city_grid_shelf_is_sticky():
    svcs = [f"svc:s{i:02d}" for i in range(25)]
    rels = [(svcs[i], svcs[i + 1], "request", "both") for i in range(24)]
    base = synthetic(svcs, rels=rels, libs=("lib:a", "lib:b"))
    before = site(base, None)
    grown = copy.deepcopy(base)
    grown["nodes"].append({"id": "lib:0", "kind": "library", "name": "lib:0"})
    after = site(grown, before)
    for k in ("lib:a", "lib:b"):
        assert after["items"][k] == before["items"][k]


def test_mapcheck_rejects_overlap_and_unplaced_children(shop_repo):
    from meaning_fixture import MEANING
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    floor = cmap["layout"]["containers"]["svc:shop"]
    ids = sorted(floor["items"])
    floor["items"][ids[1]] = dict(floor["items"][ids[0]])          # two items on one cell
    del cmap["layout"]["containers"]["site"]["items"]["svc:worker"]  # a floor-0 node with no place
    errors = "\n".join(mapcheck.check(cmap))
    assert "overlap" in errors and "svc:worker is not placed" in errors


def test_main_bus_layout_regions_unchanged_by_the_fixes():
    it = site(MAIN_BUS, None)["items"]
    assert it["svc:market"] == {"region": "line", "col": 1, "row": 0} or it["svc:market"]["col"] == 1
    assert it["svc:dash"]["region"] == "bay"


def _words(n, start=0):
    import itertools
    letters = "bcdfghjklmnpqrstvwxz"
    return ["".join(p).capitalize() + "Svc" for p in itertools.islice(itertools.product(letters, "aeiou", letters), start, start + n)]


def test_range_groups_keep_their_ids_and_members_when_a_class_is_added():
    names = _words(60)
    by_id = {f"k:{n}": {"id": f"k:{n}", "kind": "class", "name": n} for n in names}
    methods = {k: 3 for k in by_id}
    _, groups = group_children("pkg", sorted(by_id), by_id, methods)
    ranges = {g["id"]: set(g["members"]) for g in groups if g["kind"] == "range"}
    assert len(ranges) >= 3
    by_id["k:Baab"] = {"id": "k:Baab", "kind": "class", "name": "Baab"}   # sorts first
    methods["k:Baab"] = 3
    _, again = group_children("pkg", sorted(by_id), by_id, methods, previous=groups)
    after = {g["id"]: set(g["members"]) for g in again if g["kind"] == "range"}
    assert set(after) == set(ranges)
    for gid, members in ranges.items():
        assert members <= after[gid]
    assert sum("k:Baab" in m for m in after.values()) == 1


def test_an_external_with_no_lines_is_not_a_source():
    floor = site(synthetic(["svc:a", "svc:b"], ["3p:idle", "3p:in"],
                           [("svc:a", "svc:b", "request", "both"), ("3p:in", "svc:a", "stream", "forward")]), None)
    it = floor["items"]
    assert it["3p:in"]["col"] == 0 and it["3p:idle"]["col"] != 0


def test_layered_handles_a_long_chain():
    from vizcode.layout.layout import layered
    chain = [f"n{i:05d}" for i in range(3000)]
    lay = layered(chain, list(zip(chain, chain[1:])))
    assert lay[chain[-1]][0] == 2999


def test_a_new_service_takes_the_nearest_free_plot_to_its_neighbour():
    svcs = [f"svc:s{i:02d}" for i in range(45)]
    rels = [(svcs[i], svcs[i + 1], "request", "both") for i in range(44)]
    floor = site(synthetic(svcs, rels=rels, stores=()), None)
    occ = {(p["col"], p["row"]) for p in floor["items"].values() if p["region"] == "grid"}
    cols, rows = max(c for c, _ in occ) + 1, max(r for _, r in occ) + 1
    for s in ("svc:s33", "svc:s41", "svc:s05"):
        more = site(synthetic(svcs + ["svc:zz"], rels=rels + [(s, "svc:zz", "request", "both")], stores=()), floor)
        a, b = more["items"][s], more["items"]["svc:zz"]
        best = min(abs(c - a["col"]) + abs(r - a["row"]) for c in range(cols + 1) for r in range(rows + 1)
                   if (c, r) not in occ)
        assert abs(a["col"] - b["col"]) + abs(a["row"] - b["row"]) == best, s


def test_sticky_ranges_regroup_when_they_would_go_lopsided():
    names = _words(48)
    by_id = {f"k:{n}": {"id": f"k:{n}", "kind": "class", "name": n} for n in names}
    methods = {k: 3 for k in by_id}
    _, groups = group_children("pkg", sorted(by_id), by_id, methods)
    keep = sorted(by_id)[:2]
    newcomers = {f"k:Zz{w}": {"id": f"k:Zz{w}", "kind": "class", "name": f"Zz{w}"} for w in _words(30)}
    by_id2 = {k: by_id[k] for k in keep} | newcomers
    items, again = group_children("pkg", sorted(by_id2), by_id2, {k: 3 for k in by_id2}, previous=groups)
    sizes = [len(g["members"]) for g in again]
    assert len(items) >= 2 and max(sizes) <= 2 * -(-len(by_id2) // GROUP_THRESHOLD)


def test_a_floor_just_over_the_limit_groups_only_the_overflow():
    names = _words(26)
    by_id = {f"k:{n}": {"id": f"k:{n}", "kind": "method", "name": n} for n in names}
    items, groups = group_children("pkg", sorted(by_id), by_id, {k: 0 for k in by_id})
    assert len(items) <= GROUP_THRESHOLD
    assert all(len(g["members"]) >= 4 for g in groups), [len(g["members"]) for g in groups]
    loose = [i for i in items if not i.startswith("grp:")]
    assert len(loose) >= 20                      # most functions stay on the floor itself


def test_a_big_floor_still_fits_in_range_groups():
    names = _words(200)
    by_id = {f"k:{n}": {"id": f"k:{n}", "kind": "method", "name": n} for n in names}
    items, groups = group_children("pkg", sorted(by_id), by_id, {k: 0 for k in by_id})
    assert len(items) <= GROUP_THRESHOLD
    placed = [i for i in items if not i.startswith("grp:")] + [m for g in groups for m in g["members"]]
    assert sorted(placed) == sorted(by_id)


def test_an_over_grouped_floor_from_an_older_map_is_regrouped():
    names = _words(26)
    by_id = {f"k:{n}": {"id": f"k:{n}", "kind": "method", "name": n} for n in names}
    keys = sorted(by_id)
    pairs = [{"id": f"grp:pkg:range:{keys[i]}", "label": "x", "members": keys[i:i + 2], "kind": "range"}
             for i in range(0, 26, 2)]                              # 13 groups of 2, as older maps made
    items, groups = group_children("pkg", keys, by_id, {k: 0 for k in by_id}, previous=pairs)
    assert len(groups) <= 3 and len([i for i in items if not i.startswith("grp:")]) >= 20


def test_a_twin_on_a_crowded_floor_stays_out_of_groups(make_repo):
    files = {"shared/__init__.py": "", "shared/x.py": "def f():\n    pass\n"}
    for i in range(30):   # thirty top-level modules, all run by one service: a crowded service floor
        files[f"p{i:02d}/__init__.py"] = ""
        files[f"p{i:02d}/m.py"] = f"def f{i}():\n    pass\n"
    repo = make_repo(files)
    ev = [{"file": "p00/__init__.py", "line": 1}]
    cmap = assemble(structure.build(repo, "docs/viz-code"), {"nodes": [
        {"id": "svc:other", "kind": "service", "name": "other", "modules": ["shared"], "evidence": ev},
        {"id": "svc:big", "kind": "service", "name": "big", "modules": [f"p{i:02d}" for i in range(30)] + ["shared"],
         "evidence": ev}]})
    assert mapcheck.check(cmap) == []
    floor = cmap["layout"]["containers"]["svc:big"]
    assert any(i.startswith("twin:") for i in floor["items"])


def test_group_children_never_groups_a_twin():
    ids = [f"p{i:02d}::p{i:02d}/" for i in range(30)] + ["twin:shared::shared/"]
    by = {i: {"id": i, "kind": "package", "name": i.split("::")[-1]} for i in ids}
    items, groups = group_children("svc:big", sorted(ids), by, {})
    assert "twin:shared::shared/" in items and len(items) <= GROUP_THRESHOLD
    assert not any("twin:" in m for g in groups for m in g["members"])
