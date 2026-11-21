"""Twins on a crowded floor: a service that also deploys other modules gets one box per such module once their
packages crowd the floor, so its own code keeps most of the room."""
from vizcode.map import mapcheck
from vizcode.scan import structure
from vizcode.map.assemble import assemble
from vizcode.map.roles import GROUP_THRESHOLD, group_children


def _floor(own: int, twins: dict[str, int], container: str = "svc:w"):
    """A service floor with `own` packages of its own and, per module path, that many twin packages."""
    by_id = {container: {"id": container, "kind": "service", "name": "w"}}
    for i in range(own):
        pid = f"own::own.p{i:03d}/"
        by_id[pid] = {"id": pid, "kind": "package", "name": f"own.p{i:03d}"}
    for mod, n in twins.items():
        for i in range(n):
            pid = f"twin:{mod}::{mod}.p{i:03d}/"
            by_id[pid] = {"id": pid, "kind": "package", "name": f"{mod}.p{i:03d}", "module": mod, "module_label": mod}
    kids = [i for i in by_id if i != container]
    return group_children(container, kids, by_id, {}), kids


def _twin_side(items, groups):
    member = {g["id"]: g for g in groups}
    return [i for i in items if i.startswith("twin:") or all(m.startswith("twin:") for m in member.get(i, {}).get("members", ["x"]))]


def test_a_floor_of_one_modules_twins_shows_one_box_for_the_module():
    (items, groups), kids = _floor(0, {"app": 40})
    assert len(items) == 1
    (g,) = groups
    assert g["kind"] == "module" and g["label"] == "app ×40" and sorted(g["members"]) == sorted(kids)


def test_twins_crowding_the_floor_leave_the_services_own_code_most_of_the_room():
    (items, groups), kids = _floor(100, {"core": 20, "sql": 20, "net": 20})
    assert len(items) <= GROUP_THRESHOLD
    assert sorted(g["label"] for g in groups if g["kind"] == "module") == ["core ×20", "net ×20", "sql ×20"]
    assert len(_twin_side(items, groups)) == 3
    assert len(items) - 3 >= GROUP_THRESHOLD - 3 - 1   # every place the module boxes leave (name ranges may leave one)
    for g in groups:   # a group holds the service's own code or twins, never both
        assert len({m.startswith("twin:") for m in g["members"]}) == 1


def test_a_few_twins_on_a_crowded_floor_stay_loose():
    (items, groups), _ = _floor(30, {"shared": 8})
    assert len(items) <= GROUP_THRESHOLD
    assert sum(i.startswith("twin:") for i in items) == 8
    assert not any(m.startswith("twin:") for g in groups for m in g["members"])


def test_a_module_with_one_twin_keeps_it_loose():
    (items, groups), _ = _floor(0, {"app": 30, "util": 1})
    assert "twin:util::util.p000/" in items
    assert [g["label"] for g in groups] == ["app ×30"]


def test_more_twin_modules_than_room_fall_back_to_ranges_of_twins():
    (items, groups), kids = _floor(100, {f"m{i:02d}": 3 for i in range(30)})
    assert len(items) <= GROUP_THRESHOLD
    assert not any(g["kind"] == "module" for g in groups)
    placed = [i for i in items if not i.startswith("grp:")] + [m for g in groups for m in g["members"]]
    assert sorted(placed) == sorted(kids)


def test_twins_on_a_group_floor_are_never_folded_by_module_again():
    """A module box's own floor holds that module's twins: it is condensed by name ranges, never into itself."""
    twins = [f"twin:app::app.p{i:03d}/" for i in range(40)]
    by_id = {"grp:svc:w:module:app": {"id": "grp:svc:w:module:app", "kind": "group", "name": "app ×40"}}
    by_id |= {t: {"id": t, "kind": "package", "name": t[5:], "module": "app", "module_label": "app"} for t in twins}
    items, groups = group_children("grp:svc:w:module:app", twins, by_id, {})
    assert len(items) <= GROUP_THRESHOLD and groups and all(g["kind"] == "range" for g in groups)


def _worker_repo(make_repo):
    files = {"app/__init__.py": "", "jobs/__init__.py": "", "jobs/run.py": "def run():\n    pass\n"}
    for i in range(30):
        files[f"app/p{i:02d}/__init__.py"] = ""
        files[f"app/p{i:02d}/m.py"] = f"def f{i}():\n    pass\n"
    repo = make_repo(files)
    ev = [{"file": "jobs/run.py", "line": 1}]
    return assemble(structure.build(repo, "docs/viz-code"), {"nodes": [
        {"id": "svc:web", "kind": "service", "name": "web", "modules": ["app"], "evidence": ev},
        {"id": "svc:worker", "kind": "service", "name": "worker", "modules": ["jobs", "app"], "evidence": ev}]})


def test_a_worker_running_the_web_apps_code_shows_it_as_one_module_box(make_repo):
    cmap = _worker_repo(make_repo)
    assert mapcheck.check(cmap) == []
    floor = cmap["layout"]["containers"]["svc:worker"]
    (g,) = [g for g in floor["groups"] if g["kind"] == "module"]
    assert g["label"].startswith("app ×") and g["id"] in floor["items"]
    sub = cmap["layout"]["containers"][g["id"]]
    assert len(sub["items"]) <= GROUP_THRESHOLD


def test_a_twin_on_a_module_box_floor_must_be_a_twin_of_its_service(make_repo):
    cmap = _worker_repo(make_repo)
    gid = next(g["id"] for g in cmap["layout"]["containers"]["svc:worker"]["groups"] if g["kind"] == "module")
    cmap["layout"]["containers"][gid]["items"]["twin:nope"] = {"region": "line", "col": 99, "row": 99}
    assert any("twin:nope" in e for e in mapcheck.check(cmap))


def test_a_module_box_is_named_for_people():
    from vizcode.layout.layout import module_label
    assert module_label("app", "shop") == "app"
    assert module_label(".", "shop") == "shop"
    assert module_label(".#typescript", "shop") == "shop (typescript)"
    assert module_label("web#javascript", None) == "web (javascript)"
