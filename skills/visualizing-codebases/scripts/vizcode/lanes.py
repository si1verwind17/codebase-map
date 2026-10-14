"""Busy items as lanes: a floor item many others call can sit on its own lane, like a database, so its
callers tap the lane instead of running belts across the floor. Chosen only when it clearly simplifies."""
from __future__ import annotations

import itertools
import math

LANE_MIN_CALLERS = 3   # fewer callers never make a lane worth its space
LANE_CAP = 2           # lanes per floor (databases not counted)

Pt = tuple[float, float]


def _cross(p: Pt, q: Pt, r: Pt, s: Pt) -> bool:
    if len({p, q, r, s}) < 4:
        return False   # segments sharing an end meet, they do not cross
    o = lambda a, b, c: (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])  # noqa: E731
    return o(p, q, r) * o(p, q, s) < 0 and o(r, s, p) * o(r, s, q) < 0


def _segments(pos: dict[str, Pt], edges: list[tuple[str, str]], lanes: list[str]) -> list[tuple[Pt, Pt]]:
    """Straight belts between cell centres; an edge to or from a lane item becomes a vertical tap
    down to that lane, under every row."""
    bottom = max((p[1] for p in pos.values()), default=0) + 1
    lane_y = {lane: bottom + k for k, lane in enumerate(lanes)}
    segs = []
    for a, b in edges:
        if a not in pos or b not in pos or a == b:
            continue
        if a in lane_y and b in lane_y:
            continue
        if a in lane_y or b in lane_y:
            end, lane = (b, a) if a in lane_y else (a, b)
            x = pos[end][0]
            segs.append(((x, pos[end][1]), (x + 1e-6, lane_y[lane])))
        else:
            segs.append((pos[a], pos[b]))
    return segs


def crossings(pos: dict[str, Pt], edges: list[tuple[str, str]], lanes: list[str] | None = None) -> int:
    segs = _segments(pos, edges, lanes or [])
    return sum(_cross(*s, *t) for s, t in itertools.combinations(segs, 2))


def pick_lanes(pos: dict[str, Pt], edges: list[tuple[str, str]], sticky: list[str] | set[str] | frozenset = frozenset(),
               cap: int = LANE_CAP, too_busy: int | None = None, eligible: set[str] | None = None) -> list[str]:
    """Items to lift onto lanes: busiest first, each kept only when crossings drop by at least 2 and a
    quarter; items on lanes in the last map stay while they still have callers (the reader's map holds).
    `too_busy` excludes items already drawn as hub badges."""
    callers: dict[str, set[str]] = {}
    for a, b in edges:
        if a != b and a in pos and b in pos:
            callers.setdefault(b, set()).add(a)
    ordered = sticky if isinstance(sticky, list) else sorted(sticky)   # a list keeps the last map's lane order
    chosen = [s for s in ordered if len(callers.get(s, ())) >= 2][:cap]
    cur = crossings(pos, edges, chosen)
    cands = sorted((k for k, v in callers.items() if len(v) >= LANE_MIN_CALLERS and k not in chosen
                    and (too_busy is None or len(v) < too_busy) and (eligible is None or k in eligible)),
                   key=lambda k: (-len(callers[k]), k))
    for c in cands:
        if len(chosen) >= cap:
            break
        x = crossings(pos, edges, chosen + [c])
        if cur - x >= max(2, math.ceil(cur * 0.25)):
            chosen, cur = chosen + [c], x
    return chosen
