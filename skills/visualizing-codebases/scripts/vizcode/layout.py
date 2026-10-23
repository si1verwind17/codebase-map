"""Layout of every floor, computed by the scanner so positions stay put across rescans.

`layout(cmap, previous)` returns {"version": 1, "containers": {container_id: floor}} where a floor is
{"strategy", "items": {id: {"region", "col", "row"}}, "lanes": [{"id", "row"}], "groups": [...],
"utilities": [...], "hubs": [...]}. Positions are integer grid cells; the viewer turns them into pixels.
A previous layout (from the last map) keeps every surviving item where it was: only new items are placed.
"""
from __future__ import annotations

from .direction import oriented
from .lanes import pick_lanes
from .roles import HUB_FAN_IN, group_children

RUNTIME = {"request", "event", "stream", "batch", "ext-call", "db-read", "db-write"}
CITY_GRID_ABOVE = 20
SITE = "site"
HORIZONTAL = ("shelf", "bay", "hubs", "bus", "airfield")  # regions that spread along a row; the others stack down a column


# ---------------------------------------------------------------- layered core
def layered(nodes: list[str], edges: list[tuple[str, str]]) -> dict[str, tuple[int, int]]:
    """Deterministic layered placement: (layer, order) per node. Cycles are broken by DFS in id order."""
    nodes = sorted(set(nodes))
    adj: dict[str, list[str]] = {n: [] for n in nodes}
    for a, b in sorted(set(edges)):
        if a != b and a in adj and b in adj:
            adj[a].append(b)
    state, dag = {}, {n: [] for n in nodes}

    def dfs(start: str) -> None:   # iterative: a long chain must not hit the recursion limit
        state[start] = 1
        stack = [(start, iter(adj[start]))]
        while stack:
            u, it = stack[-1]
            v = next(it, None)
            if v is None:
                state[u] = 2
                stack.pop()
            elif state.get(v) == 1:
                dag[v].append(u)          # back edge: reverse it
            else:
                dag[u].append(v)
                if v not in state:
                    state[v] = 1
                    stack.append((v, iter(adj[v])))

    for n in nodes:
        if n not in state:
            dfs(n)
    preds: dict[str, list[str]] = {n: [] for n in nodes}
    for u, vs in dag.items():
        for v in vs:
            preds[v].append(u)
    layer: dict[str, int] = {}
    indeg = {n: len(preds[n]) for n in nodes}
    ready = [n for n in nodes if not indeg[n]]
    while ready:                   # longest path from a source, in topological order (the dag is acyclic)
        u = ready.pop()
        layer[u] = max((layer[p] + 1 for p in preds[u]), default=0)
        for v in dag[u]:
            indeg[v] -= 1
            if not indeg[v]:
                ready.append(v)
    by_layer: dict[int, list[str]] = {}
    for n in nodes:
        by_layer.setdefault(layer[n], []).append(n)
    order = {n: i for lst in by_layer.values() for i, n in enumerate(sorted(lst))}
    succ = {n: dag[n] for n in nodes}
    for sweep in range(4):
        rng = sorted(by_layer) if sweep % 2 == 0 else sorted(by_layer, reverse=True)
        for L in rng:
            def bary(n: str) -> float:
                nb = preds[n] if sweep % 2 == 0 else succ[n]
                return sum(order[x] for x in nb) / len(nb) if nb else order[n]
            by_layer[L].sort(key=lambda n: (bary(n), order[n], n))
            for i, n in enumerate(by_layer[L]):
                order[n] = i
    return {n: (layer[n], order[n]) for n in nodes}


# ---------------------------------------------------------------- sticky merge
MAX_ROWS = 6   # a layer taller than this wraps into extra columns: a floor should read wide, not as one tall list


def wrap_columns(lay: dict[str, tuple[int, int]], max_rows: int = MAX_ROWS) -> dict[str, tuple[int, int]]:
    """(layer, order) -> (col, row): a layer with more than max_rows items spreads over ceil(n/max_rows)
    columns, and every later layer shifts right to make room."""
    by_layer: dict[int, list[tuple[int, str]]] = {}
    for n, (layer, order) in lay.items():
        by_layer.setdefault(layer, []).append((order, n))
    cells, col = {}, 0
    for layer in sorted(by_layer):
        ordered = [n for _, n in sorted(by_layer[layer])]
        for i, n in enumerate(ordered):
            cells[n] = (col + i // max_rows, i % max_rows)
        col += -(-len(ordered) // max_rows)
    return cells


def merge(fresh: dict[str, dict], prev: dict[str, dict] | None) -> dict[str, dict]:
    """Survivors keep their previous cell; new items take their fresh cell, moved down (or right on
    horizontal regions) until free. Removed items leave their cell empty."""
    if not prev:
        return fresh
    out = {i: dict(prev[i]) for i in fresh if i in prev and prev[i].get("region") == fresh[i].get("region")}
    taken = {(p["region"], p["col"], p["row"]) for p in out.values()}
    for i in sorted(fresh):
        if i in out:
            continue
        p = dict(fresh[i])
        horizontal = p["region"] in HORIZONTAL
        while (p["region"], p["col"], p["row"]) in taken:
            if horizontal:
                p["col"] += 1
            else:
                p["row"] += 1
        taken.add((p["region"], p["col"], p["row"]))
        out[i] = p
    return out


# ---------------------------------------------------------------- floor 0
def _root(nid: str, by_id: dict[str, dict], kinds: set[str]) -> str | None:
    n = by_id.get(nid)
    while n is not None and n["kind"] not in kinds and n.get("parent"):
        n = by_id.get(n["parent"])
    return n["id"] if n is not None and n["kind"] in kinds else None


def _store_of(nid: str, by_id: dict[str, dict]) -> str:
    n = by_id[nid]
    if n["kind"] == "topic":
        return "broker:" + nid.split(":")[1] if nid.count(":") >= 2 else nid
    return nid


def site(cmap: dict, prev: dict | None) -> dict:
    by_id = {n["id"]: n for n in cmap["nodes"]}
    top = {"service", "library", "external", "topic", "datastore"}
    rels = []
    for r in cmap["relations"]:
        if r["kind"] not in RUNTIME:
            continue
        a, b = _root(r["from"], by_id, top), _root(r["to"], by_id, top)
        if a and b and a != b:
            rels.append({**r, "from": a, "to": b})
    services = sorted(n["id"] for n in cmap["nodes"] if n["kind"] == "service")
    externals = sorted(n["id"] for n in cmap["nodes"] if n["kind"] == "external")
    libraries = sorted(n["id"] for n in cmap["nodes"] if n["kind"] == "library")
    stores = {n["id"] for n in cmap["nodes"] if n["kind"] in ("datastore", "topic")}
    # shared utilities: externals only ext-called, by 3+ callers, never a source
    utilities = sorted(x for x in externals
                       if len({r["from"] for r in rels if r["to"] == x}) >= 3
                       and all(r["kind"] == "ext-call" for r in rels if r["to"] == x)
                       and not any(r["from"] == x for r in rels))
    # observers (read-only bay): services with no effects that read a store, or only call such
    # services; never a service that a line service or an external sends work to
    effects = {s for s in services for r in rels if r["from"] == s and r["to"] not in utilities
               and r["kind"] in ("db-write", "ext-call", "stream", "batch", "event")}
    calm = [s for s in services if s not in effects]
    obs = {s for s in calm if any(r["from"] == s and r["kind"] == "db-read" for r in rels)}
    grew = True
    while grew:
        grew = False
        for s in calm:
            targets = {r["to"] for r in rels if r["from"] == s and r["kind"] == "request"}
            if s not in obs and targets and targets <= obs:
                obs.add(s)
                grew = True
    shrank = True
    while shrank:
        shrank = False
        for s in sorted(obs):
            fed = [r for r in rels if r["kind"] in ("request", "event", "stream", "batch")
                   and oriented(r)[1] == s and oriented(r)[0] not in obs and r["from"] not in stores
                   and r["to"] not in stores]
            if fed:
                obs.discard(s)
                shrank = True
    line = [s for s in services if s not in obs] + [x for x in externals if x not in utilities]
    line_set = set(line)
    edges = [oriented(r) for r in rels if r["from"] in line_set and r["to"] in line_set]
    for t in sorted(n["id"] for n in cmap["nodes"] if n["kind"] == "topic"):  # events: producer → consumer
        ends = [oriented(r) for r in rels if t in (r["from"], r["to"])]
        producers = sorted({a for a, b in ends if b == t and a in line_set})
        consumers = sorted({b for a, b in ends if a == t and b in line_set})
        edges += [(p, c) for p in producers for c in consumers if p != c]
    if len(services) > CITY_GRID_ABOVE:
        return city_grid(cmap, prev, rels, services, externals, libraries, stores, utilities)
    # a source sends and never receives; an external with no lines at all is not one
    sources = {x for x in externals if x in line_set and any(x in e for e in edges)
               and all(a == x for a, b in edges if x in (a, b))}
    sinks = {x for x in externals if x in line_set and x not in sources}
    inner_line = [n for n in line if n not in sources and n not in sinks]
    lay = layered(inner_line, [(a, b) for a, b in edges if a in inner_line and b in inner_line])
    for x in sorted(sources | sinks):  # yards: rows follow the services they touch
        nb = [lay[o][1] for a, b in edges for o in (a, b) if x in (a, b) and o != x and o in lay]
        lay[x] = (0, round(sum(nb) / len(nb)) if nb else 0)
    shift = 1 if sources else 0
    last = max([lay[n][0] + shift for n in line if n not in sources and n not in sinks] or [0])
    items: dict[str, dict] = {}
    for n in line:
        col = 0 if n in sources else (last + 1 if n in sinks else lay[n][0] + shift)
        items[n] = {"region": "line", "col": col, "row": lay[n][1]}
    # bus lanes: one per datastore / broker, busiest first
    taps: dict[str, int] = {}
    for r in rels:
        for end in (r["from"], r["to"]):
            if end in stores:
                taps[_store_of(end, by_id)] = taps.get(_store_of(end, by_id), 0) + 1
    lane_ids = sorted({_store_of(s, by_id) for s in stores}, key=lambda s: (-taps.get(s, 0), s))
    prev_lanes = {l["id"]: l["row"] for l in (prev or {}).get("lanes", [])}
    lanes, used = [], set(prev_lanes.values())
    for lid in lane_ids:
        if lid in prev_lanes:
            row = prev_lanes[lid]
        else:
            row = 0
            while row in used:
                row += 1
            used.add(row)
        lanes.append({"id": lid, "row": row})
    lanes.sort(key=lambda l: l["row"])
    lane_row = {l["id"]: l["row"] for l in lanes}
    for s in sorted(stores):
        lid = _store_of(s, by_id)
        if by_id[s]["kind"] == "datastore":
            items[s] = {"region": "bus", "col": last + 2, "row": lane_row[lid]}
        else:  # a topic hub sits on its broker's lane under the services that use it
            cols = [items[r["from"]]["col"] if r["to"] == s else items[r["to"]]["col"] for r in rels
                    if s in (r["from"], r["to"]) and (r["from"] in items or r["to"] in items)]
            items[s] = {"region": "bus", "col": round(sum(cols) / len(cols)) if cols else 0, "row": lane_row[lid]}
    for i, s in enumerate(sorted(obs)):
        items[s] = {"region": "bay", "col": i, "row": 0}
    users = {}
    for r in cmap["relations"]:
        if r["kind"] == "uses-code" and r["to"] in libraries and r["from"] in items:
            users.setdefault(r["to"], []).append(items[r["from"]]["col"])
    for lib in libraries:
        cols = users.get(lib, [])
        items[lib] = {"region": "shelf", "col": round(sum(cols) / len(cols)) if cols else 0, "row": 0}
    # a service many others call can take a lane below the databases when that untangles the line
    lanes += _lift_busy(items, edges, prev, None, max([l["row"] for l in lanes], default=-1) + 1, set(services))
    items = merge(_dedupe(items), (prev or {}).get("items") if (prev or {}).get("strategy") == "main-bus" else None)
    return {"strategy": "main-bus", "items": items, "lanes": lanes, "groups": [], "utilities": utilities, "hubs": []}


def _dedupe(items: dict[str, dict]) -> dict[str, dict]:
    """Fresh placement can stack two items on one cell (e.g. shelf by mean column); spread them."""
    out, taken = {}, set()
    for i in sorted(items, key=lambda k: (items[k]["region"], items[k]["col"], items[k]["row"], k)):
        p = dict(items[i])
        horizontal = p["region"] in HORIZONTAL
        while (p["region"], p["col"], p["row"]) in taken:
            if horizontal:
                p["col"] += 1
            else:
                p["row"] += 1
        taken.add((p["region"], p["col"], p["row"]))
        out[i] = p
    return out


def city_grid(cmap, prev, rels, services, externals, libraries, stores, utilities) -> dict:
    """Plots on a grid, most-connected first, each next service beside its placed neighbours."""
    blocks = services + [x for x in externals if x not in utilities] + sorted(s for s in stores)
    weight: dict[tuple[str, str], int] = {}
    for r in rels:
        if r["from"] in blocks and r["to"] in blocks:
            k = tuple(sorted((r["from"], r["to"])))
            weight[k] = weight.get(k, 0) + 1
    degree = {b: sum(w for k, w in weight.items() if b in k) for b in blocks}
    side = max(2, int(len(blocks) ** 0.5 + 0.999))
    placed: dict[str, tuple[int, int]] = {}
    prev_items = (prev or {}).get("items") if (prev or {}).get("strategy") == "city-grid" else None
    if prev_items:
        placed = {b: (p["col"], p["row"]) for b, p in prev_items.items() if b in blocks}
    free = lambda c: c not in placed.values()  # noqa: E731
    for b in sorted([b for b in blocks if b not in placed], key=lambda b: (-degree[b], b)):
        nbrs = [placed[o] for k in weight for o in k if b in k and o != b and o in placed]
        if not placed:
            cell = (side // 2, side // 2)
        else:
            cols = max([side + 1] + [c + 1 for c, _ in placed.values()])   # a sticky grid can outgrow `side`
            rows = max([side + 1] + [r + 1 for _, r in placed.values()])
            cands = [(c, r) for c in range(cols + 1) for r in range(rows + 1) if free((c, r))]
            tx = sum(x for x, _ in nbrs) / len(nbrs) if nbrs else side / 2
            ty = sum(y for _, y in nbrs) / len(nbrs) if nbrs else side / 2
            cell = min(cands, key=lambda c: (abs(c[0] - tx) + abs(c[1] - ty), c[1], c[0]))
        placed[b] = cell
    items = {b: {"region": "grid", "col": c, "row": r} for b, (c, r) in placed.items()}
    shelf = {lib: {"region": "shelf", "col": i, "row": 0} for i, lib in enumerate(libraries)}
    items.update(merge(shelf, {k: v for k, v in (prev_items or {}).items() if v.get("region") == "shelf"}))
    return {"strategy": "city-grid", "items": items, "lanes": [], "groups": [], "utilities": utilities, "hubs": []}


# ---------------------------------------------------------------- inner floors
def inner(container: str, children: list[str], cmap: dict, roles: dict[str, str], by_id: dict[str, dict],
          call_edges: list[tuple[str, str]], method_count: dict[str, int], prev: dict | None) -> dict:
    """`call_edges`: the calls between two different children of the floor's base container (layout: each call
    is lifted once, to the children of its two ends' lowest common container), as those children."""
    kind = by_id[container]["kind"]
    if kind == "datastore":  # warehouse shelves: tables in rows of four
        items = {t: {"region": "shelf", "col": i % 4, "row": i // 4} for i, t in enumerate(sorted(children))}
        return {"strategy": "shelves", "items": merge(items, (prev or {}).get("items")), "lanes": [], "groups": [],
                "utilities": [], "hubs": []}
    # in-process queues stand on the floor's own airfield, in a row, never grouped
    queues = sorted(c for c in children if by_id[c]["kind"] == "in-process-queue")
    children = [c for c in children if c not in queues]
    top_items, groups = group_children(container, children, by_id, method_count, (prev or {}).get("groups"))
    member_of = {m: g["id"] for g in groups for m in g["members"]}

    child_set = set(children)

    def lift(x: str) -> str | None:
        return member_of.get(x, x) if x in child_set else None

    edges = [(a2, b2) for a, b in call_edges if (a2 := lift(a)) and (b2 := lift(b)) and a2 != b2]
    fan_in: dict[str, set[str]] = {}
    for a, b in edges:
        fan_in.setdefault(b, set()).add(a)
    hubs = sorted(x for x, srcs in fan_in.items() if len(srcs) >= HUB_FAN_IN)
    edges = [(a, b) for a, b in edges if b not in hubs]
    items: dict[str, dict] = {}
    if kind in ("service", "library"):
        strategy, band = "bands", {"entry": 0, "logic": 1, "outbound": 2}
        group_role = {}
        for g in groups:
            votes = [roles.get(m, "logic") for m in g["members"]]
            group_role[g["id"]] = max(sorted(set(votes)), key=votes.count)
        role_of = lambda i: group_role.get(i) or roles.get(i, "logic")  # noqa: E731
        lay = wrap_columns(layered([i for i in top_items if role_of(i) == "logic" and i not in hubs], edges))
        rows = {0: 0, 2: 0}
        for i in top_items:
            role = role_of(i)
            if i in hubs:
                items[i] = {"region": "hubs", "col": 0, "row": 0}
            elif role == "storage":
                items[i] = {"region": "bus", "col": 0, "row": 0}
            elif role == "model":
                items[i] = {"region": "shelf", "col": 0, "row": 0}
            elif role == "logic":
                items[i] = {"region": "line", "col": 1 + lay[i][0], "row": lay[i][1]}
            else:
                c = band[role] if role == "entry" else 99
                items[i] = {"region": "line", "col": c, "row": rows[band[role]]}
                rows[band[role]] += 1
        last = max([p["col"] for p in items.values() if p["region"] == "line" and p["col"] != 99] or [0])
        for p in items.values():
            if p["col"] == 99:
                p["col"] = last + 1
    else:
        strategy = "layered"
        lay = wrap_columns(layered([i for i in top_items if i not in hubs], edges))
        for i in top_items:
            items[i] = {"region": "hubs", "col": 0, "row": 0} if i in hubs else {"region": "line", "col": lay[i][0], "row": lay[i][1]}
    lanes = _lift_busy(items, edges, prev, HUB_FAN_IN)
    items.update({q: {"region": "airfield", "col": i, "row": 0} for i, q in enumerate(queues)})
    items = merge(_dedupe(items), (prev or {}).get("items") if (prev or {}).get("strategy") == strategy else None)
    return {"strategy": strategy, "items": items, "lanes": lanes, "groups": groups, "utilities": [], "hubs": hubs}


def _lift_busy(items: dict[str, dict], edges: list[tuple[str, str]], prev: dict | None, too_busy: int | None,
               first_row: int = 0, eligible: set[str] | None = None) -> list[dict]:
    """Busy line items whose belts tangle the floor move onto their own lane (region `lane`); returns the
    lanes. Only when crossings clearly drop (see lanes.pick_lanes); a lane from the last map is kept."""
    pos = {i: (p["col"], p["row"]) for i, p in items.items() if p["region"] == "line"}
    prev_lanes = sorted((l for l in (prev or {}).get("lanes", []) if l["id"] in pos), key=lambda l: l["row"])
    chosen = pick_lanes(pos, [(a, b) for a, b in edges if a in pos and b in pos], [l["id"] for l in prev_lanes],
                        too_busy=too_busy, eligible=eligible)
    prev_row = {l["id"]: l["row"] for l in prev_lanes}
    used = {prev_row[c] for c in chosen if c in prev_row}
    lanes = []
    for c in chosen:   # a lane keeps its row across rescans; a new one takes the next free row
        row = prev_row.get(c)
        if row is None:
            row = first_row
            while row in used:
                row += 1
            used.add(row)
        items[c] = {"region": "lane", "col": 0, "row": row}
        lanes.append({"id": c, "row": row})
    return lanes


# ---------------------------------------------------------------- entry point
def layout(cmap: dict, roles: dict[str, str], previous: dict | None = None) -> dict:
    by_id = {n["id"]: n for n in cmap["nodes"]}
    prev_c = (previous or {}).get("containers", {})
    children: dict[str, list[str]] = {}
    method_count: dict[str, int] = {}
    for n in cmap["nodes"]:
        if n.get("parent"):
            children.setdefault(n["parent"], []).append(n["id"])
        for t in n.get("twins", []):   # a module this service also deploys: a twin of its root package
            tid = f"twin:{t}"
            children.setdefault(n["id"], []).append(tid)
            by_id[tid] = {**by_id[t], "id": tid, "parent": n["id"]}
        if n["kind"] == "method" and n.get("parent"):
            method_count[n["parent"]] = method_count.get(n["parent"], 0) + 1
    paths: dict[str, list[str]] = {}

    def path(x: str) -> list[str]:
        """x's ancestors from the top down, x last."""
        if x not in paths:
            out, n, seen = [], by_id.get(x), set()
            while n is not None and n["id"] not in seen:
                seen.add(n["id"])
                out.append(n["id"])
                n = by_id.get(n.get("parent") or "")
            paths[x] = out[::-1]
        return paths[x]

    # a call shows on one floor only: its two ends' lowest common container, between the children they sit under
    lifted: dict[str, list[tuple[str, str]]] = {}
    for a, b in sorted((r["from"], r["to"]) for r in cmap["relations"] if r["kind"] == "calls"):
        pa, pb = path(a), path(b)
        i = 0
        while i < len(pa) and i < len(pb) and pa[i] == pb[i]:
            i += 1
        if 0 < i < len(pa) and i < len(pb):
            lifted.setdefault(pa[i - 1], []).append((pa[i], pb[i]))
    containers = {SITE: site(cmap, prev_c.get(SITE))}
    for cid in sorted(children):
        if by_id[cid]["kind"] == "method":
            continue
        floor = inner(cid, children[cid], cmap, roles, by_id, lifted.get(cid, []), method_count, prev_c.get(cid))
        containers[cid] = floor
        queue = list(floor["groups"])
        while queue:  # a group opens as its own sub-assembly floor, condensed again when crowded
            g = queue.pop(0)
            by_id[g["id"]] = {"id": g["id"], "kind": "group", "name": g["label"], "parent": cid}
            sub = inner(g["id"], g["members"], cmap, roles, by_id, lifted.get(cid, []), method_count,
                        prev_c.get(g["id"]))
            containers[g["id"]] = sub
            queue += sub["groups"]
    return {"version": 1, "containers": containers}
