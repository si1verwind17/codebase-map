#!/usr/bin/env python3
"""Write a synthetic big code map to profile the viewer on: one large service with a few very busy floors.

Usage: big_map.py [--out viewer/.profile/big.code-map.json] [--scale 1.0] [--seed 1]
The structure is hand-made like the field guide's maps (guide_maps.Code) and goes through the skill's own pipeline
(`assemble`, then `mapcheck`), so layout, range groups, lanes and hubs are the real ones. At scale 1 it is as big as
the real maps that showed the lag (~15k nodes, ~12k relations, 3,000+ floors), with a few hot clusters of
consecutive packages that call widely: range-group floors with thousands of relations and many doors. Deterministic:
the same scale and seed give the same bytes. Scale 1 takes about 100 s (the layout
of 3,000+ floors).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide_maps import SCANNED_AT, Code, ev, rel, service  # noqa: E402
from vizcode.map import mapcheck  # noqa: E402
from vizcode.map.assemble import assemble  # noqa: E402
from vizcode.map.roles import GROUP_THRESHOLD, RANGE_MIN  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / ".profile" / "big.code-map.json"
PACKAGES = 300       # in `api`, at scale 1
FILES = 5            # per package, each with one class
METHODS = 8          # per class
LOCAL_CALL = 0.4     # chance an ordinary method calls another in its package
NEAR_CALL = 0.1      # ... and one in a nearby package
HOT_CLUSTERS = 3     # runs of consecutive packages that call widely
HOT_SIZE = 9         # packages per run
HOT_FANOUT = 6       # calls per method in a hot package
HOT_REACH = 20       # far packages a run calls: a door each on its floor (all 300 make a floor take 10 s to plan,
                     # 20 about 0.5-1 s, as on the real maps)
DB, TABLE, TOPIC = "db:sql:DB_URL", "db:sql:DB_URL/public.records", "topic:events:records"


def _pkg(i: int) -> str:
    return f"core.p{i:03d}"


def _method(i: int, f: int, m: int) -> str:
    return f"run_{i:03d}_{f}_{m}"


def _hot(n: int) -> list[list[int]]:
    """The hot runs of packages: spread evenly over `api`, as many and as long as scale 1 makes them, fewer and shorter
    on a smaller map (so they stay a small share of it)."""
    runs = max(1, min(HOT_CLUSTERS, round(HOT_CLUSTERS * n / PACKAGES)))
    size = max(1, min(HOT_SIZE, round(HOT_SIZE * n / PACKAGES)))
    loose, per = _ranges(n)
    starts = [(k + 1) * n // (runs + 1) - size // 2 for k in range(runs)]
    if per >= size:   # snap each run inside one range group, so its floor holds the whole run
        starts = [min(n - size, loose + (s - loose) // per * per) for s in starts]
    return [list(range(s, s + size)) for s in starts]


def _ranges(n: int) -> tuple[int, int]:
    """(loose packages before the first range group, packages per range group) on a floor of `n` packages, as
    roles.group_children splits it; (0, 0) when the floor needs no groups."""
    if n <= GROUP_THRESHOLD:
        return 0, 0
    size = max(RANGE_MIN, -(-n // GROUP_THRESHOLD))
    count = min(-(-(n - GROUP_THRESHOLD) // (size - 1)), -(-n // size))
    tail = min(n, count * size)
    return n - tail, -(-tail // count)


def _structure(scale: float, rng: random.Random) -> tuple[dict, dict]:
    c = Code("big")
    c.module("api")
    n = max(4, round(PACKAGES * scale))
    hot: dict[int, list[int]] = {}   # hot package -> the far packages its run calls
    for run in _hot(n):
        far = sorted(rng.sample([i for i in range(n) if i not in run], min(HOT_REACH, n - len(run))))
        hot.update(dict.fromkeys(run, far))
    ids: dict[tuple[int, int, int], str] = {}
    for i in range(n):
        pkg = c.package("api", _pkg(i))
        for f in range(FILES):
            route = ("POST", f"/v1/p{i:03d}") if i == 0 and f == 0 else None
            sink = "sql-db" if i == n - 1 and f == 0 else None
            owner = c.cls(c.file(pkg, f"f{f}", route=route, sink=sink), f"Unit{i:03d}x{f}")
            for m in range(METHODS):
                ids[i, f, m] = c.method(owner, _method(i, f, m), (("x", "int"),), "int")
    for i, f, m in sorted(ids):
        caller = ids[i, f, m]
        if i in hot:   # a hot package calls a lot, out to the far packages its run calls
            for _ in range(HOT_FANOUT):
                c.call(caller, _method(rng.choice(hot[i]), rng.randrange(FILES), rng.randrange(METHODS)), 1)
            continue
        if rng.random() < LOCAL_CALL:
            c.call(caller, _method(i, rng.randrange(FILES), rng.randrange(METHODS)), 1)
        if rng.random() < NEAR_CALL:
            j = min(n - 1, max(0, i + rng.choice((-2, -1, 1, 2))))
            c.call(caller, _method(j, rng.randrange(FILES), rng.randrange(METHODS)), 1)
    entry, store = ids[0, 0, 0], ids[n - 1, 0, 0]
    jobs = _small(c, "jobs", "on_record")
    admin = _small(c, "admin", "audit")
    gateway = _small(c, "gateway", "forward")
    meaning = {"nodes": [service("api", 2), service("jobs", 3), service("admin", 4), service("gateway", 5),
                         {"id": DB, "kind": "datastore", "name": "records-db"},
                         {"id": TABLE, "kind": "table", "parent": DB, "name": "public.records"},
                         {"id": TOPIC, "kind": "topic", "name": "records", "delivery": "fan-out",
                          "evidence": ev("deploy/topics.yaml", 2)}],
               "relations": [rel("db-write", store, TABLE, "table public.records", f"api/core/p{n - 1:03d}/f0.py"),
                             rel("db-read", jobs[1], TABLE, "table public.records", "jobs/api/routes.py"),
                             rel("event", store, TOPIC, "records", f"api/core/p{n - 1:03d}/f0.py"),
                             rel("event", TOPIC, jobs[0], "records", "jobs/api/routes.py", group="jobs"),
                             rel("event", TOPIC, admin[0], "records", "admin/api/routes.py", group="admin"),
                             rel("request", gateway[1], entry, "POST /v1/p000", "gateway/api/routes.py",
                                 data="forward"),
                             rel("request", admin[1], entry, "POST /v1/p000", "admin/api/routes.py",
                                 data="forward")]}
    return c.structure(), meaning


def _small(c: Code, name: str, handler: str) -> tuple[str, str]:
    """A small service: an entry file with its handler and a second method, and a logic package it calls."""
    c.module(name)
    routes = c.file(c.package(name, "api"), "routes", route=("POST", f"/v1/{name}"))
    first = c.method(routes, handler, (("body", "dict"),), "dict")
    second = c.method(routes, f"{name}_send", (("body", "dict"),), "dict")
    logic = c.file(c.package(name, "logic"), "steps")
    for k in range(3):
        c.method(logic, f"{name}_step_{k}", (("body", "dict"),), "dict")
        c.call(first, f"{name}_step_{k}", 1)
    return first, second


def build(scale: float = 1.0, seed: int = 1) -> dict:
    """The map, checked; raises ValueError when mapcheck fails."""
    structure, meaning = _structure(scale, random.Random(seed))
    cmap = assemble(structure, {"domain_context": None, **meaning})
    cmap["meta"]["scanned_at"] = SCANNED_AT   # fixed, so the same scale and seed give the same bytes
    cmap["meta"].pop("rules_version")
    cmap["meta"].pop("stack", None)
    if errors := mapcheck.check(cmap):
        raise ValueError("; ".join(errors))
    _check_runs(cmap, max(4, round(PACKAGES * scale)))
    return cmap


def _check_runs(cmap: dict, n: int) -> None:
    """Each hot run in one range group of `api`'s floor: `_ranges` copies roles.group_children's arithmetic, and a
    change there would split the runs (and their busy floors) without this."""
    groups = cmap["layout"]["containers"]["svc:api"]["groups"]
    if not groups:
        return
    group_of = {m: g["id"] for g in groups for m in g["members"]}
    for run in _hot(n):
        held = {group_of.get(f"api::{_pkg(i)}/") for i in run}
        if len(held) != 1 or None in held:
            raise ValueError(f"hot run {_pkg(run[0])}–{_pkg(run[-1])} spans range groups {sorted(map(str, held))}: "
                             "big_map._ranges no longer matches roles.group_children")


def relations_inside(cmap: dict) -> dict[str, int]:
    """Relations per floor with an end on it: the end is the floor's container or under it, through parents or
    through a group's members."""
    parent = {n["id"]: n.get("parent") for n in cmap["nodes"]}
    groups: dict[str, list[str]] = {}   # member -> the groups holding it (a range group's floor can group again)
    for floor in cmap["layout"]["containers"].values():
        for g in floor.get("groups", []):
            for m in g["members"]:
                groups.setdefault(m, []).append(g["id"])
    memo: dict[str, frozenset[str]] = {}

    def above(x: str) -> frozenset[str]:
        if x not in memo:
            out = {x, *groups.get(x, [])}
            for g in groups.get(x, []):
                out |= above(g)
            if parent.get(x):
                out |= above(parent[x])
            memo[x] = frozenset(out)
        return memo[x]

    counts = dict.fromkeys(cmap["layout"]["containers"], 0)
    for r in cmap["relations"]:
        for floor in above(r["from"]) | above(r["to"]):
            if floor in counts:
                counts[floor] += 1
    return counts


def busiest_floor(cmap: dict) -> str:
    """The busiest floor one below the busiest item on the site: where a cold entry costs the most."""
    inside, floors = relations_inside(cmap), cmap["layout"]["containers"]
    top = max((i for i in floors["site"]["items"] if i in floors), key=lambda i: (inside[i], i))
    return max((i for i in floors[top]["items"] if i in floors), key=lambda i: (inside[i], i))


def stats(cmap: dict) -> dict:
    """Size of the map and its five busiest floors (by relations inside), as the targets in the tests are stated."""
    inside = relations_inside(cmap)
    return {"nodes": len(cmap["nodes"]), "relations": len(cmap["relations"]), "floors": len(cmap["layout"]["containers"]),
            "busiest": sorted(inside.items(), key=lambda kv: (-kv[1], kv[0]))[:5]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    try:
        cmap = build(a.scale, a.seed)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(cmap, indent=1) + "\n", encoding="utf-8")
    print(f"{a.out}: {json.dumps(stats(cmap))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
