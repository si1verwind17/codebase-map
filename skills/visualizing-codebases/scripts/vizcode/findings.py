"""Findings: what we observe about the user's code, read from the map. Part 1 has the cycle finding."""
from __future__ import annotations

CALL_KINDS = ("request", "stream")


def cycles(cmap: dict) -> list[dict]:
    """Service loops over request and stream relations: one entry per strongly connected component of 2+, as its
    shortest loop through the smallest id (`services`, `relations`) and the group's other services (`others`)."""
    nodes = {n["id"]: n for n in cmap.get("nodes", [])}

    def service_of(nid: str) -> str | None:
        seen: set[str] = set()
        while nid in nodes and nid not in seen:
            seen.add(nid)
            if nodes[nid]["kind"] == "service":
                return nid
            nid = nodes[nid].get("parent")
        return None

    edges: dict[str, dict[str, list[str]]] = {}
    for r in cmap.get("relations", []):
        if r["kind"] not in CALL_KINDS:
            continue
        a, b = service_of(r["from"]), service_of(r["to"])
        if a and b and a != b:
            edges.setdefault(a, {}).setdefault(b, []).append(r["id"])
            edges.setdefault(b, {})
    # Tarjan, iterative
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    sccs: list[list[str]] = []
    for root in sorted(edges):
        if root in index:
            continue
        work = [(root, iter(sorted(edges[root])))]
        index[root] = low[root] = len(index)
        stack.append(root); on.add(root)
        while work:
            v, it = work[-1]
            for w in it:
                if w not in index:
                    index[w] = low[w] = len(index)
                    stack.append(w); on.add(w)
                    work.append((w, iter(sorted(edges[w]))))
                    break
                if w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop(); on.discard(w); comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        sccs.append(comp)
    found = []
    for comp in sccs:
        members = set(comp)
        start = min(members)
        loop = _loop_through(start, members, edges)
        rels = [edges[a][b][0] for a, b in zip(loop, loop[1:] + loop[:1])]
        found.append({"services": loop, "relations": rels, "others": sorted(members - set(loop))})
    return sorted(found, key=lambda c: c["services"])


def _loop_through(start: str, members: set[str], edges: dict[str, dict[str, list[str]]]) -> list[str]:
    """Shortest loop start -> ... -> start inside the component, ties broken by smallest id."""
    prev: dict[str, str] = {}
    frontier = [start]
    while frontier:
        nxt = []
        for v in frontier:
            for w in sorted(edges[v]):
                if w == start:
                    path = [v]
                    while path[-1] != start:
                        path.append(prev[path[-1]])
                    return path[::-1]
                if w in members and w not in prev and w != start:
                    prev[w] = v
                    nxt.append(w)
        frontier = nxt
    return [start]
