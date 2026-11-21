"""Package roles (where a package sits on the production line) and crowd grouping."""
from __future__ import annotations

import re

from ..scan.adapters import without_suffix

ROLES = ("entry", "logic", "outbound", "storage", "model")
STORAGE_SINKS = {"sql-db", "doc-db", "cache"}
OUTBOUND_SINKS = {"http-out", "grpc", "event", "cloud-sdk", "mail"}
GROUP_THRESHOLD = 24
HUB_FAN_IN = 8
FAMILY_MIN = 3
RANGE_MIN = 4          # a range group of fewer items hides more than it saves


def package_of(node_id: str, by_id: dict[str, dict]) -> str | None:
    n = by_id.get(node_id)
    while n is not None and n["kind"] != "package":
        n = by_id.get(n.get("parent") or "")
    return n["id"] if n else None


def package_roles(nodes: list[dict], files: dict[str, dict], facts: dict[str, dict],
                  overrides: dict[str, dict] | None = None) -> dict[str, str]:
    """Role per package from its files' facts; meaning-pass overrides win."""
    by_id = {n["id"]: n for n in nodes}
    signals: dict[str, set[str]] = {}
    for f, info in files.items():
        pkg = package_of(info["node"], by_id)
        if pkg is None:
            continue
        s = signals.setdefault(pkg, set())
        ff = facts.get(f, {})
        if ff.get("routes"):
            s.add("entry")
        kinds = {x["kind"] for x in ff.get("sinks", [])}
        if kinds & STORAGE_SINKS or ff.get("sql"):
            s.add("storage")
        if kinds & OUTBOUND_SINKS:
            s.add("outbound")
    methods_per_owner: dict[str, int] = {}
    owners_per_pkg: dict[str, set[str]] = {}
    for n in nodes:
        if n["kind"] in ("class", "file"):
            pkg = package_of(n["id"], by_id)
            if pkg:
                owners_per_pkg.setdefault(pkg, set()).add(n["id"])
                methods_per_owner.setdefault(n["id"], 0)
        elif n["kind"] == "method" and n.get("parent") in by_id:
            methods_per_owner[n["parent"]] = methods_per_owner.get(n["parent"], 0) + 1
    roles = {}
    for n in nodes:
        if n["kind"] != "package":
            continue
        s = signals.get(n["id"], set())
        owners = owners_per_pkg.get(n["id"], set())
        if "entry" in s:
            role = "entry"
        elif "storage" in s:
            role = "storage"
        elif "outbound" in s:
            role = "outbound"
        elif owners and any(by_id[o]["kind"] == "class" for o in owners) and all(
                methods_per_owner.get(o, 0) <= (1 if by_id[o]["kind"] == "class" else 0) for o in owners):
            role = "model"  # only data classes: no class has more than one method, no file has functions
        else:
            role = "logic"
        roles[n["id"]] = role
    for pkg, o in (overrides or {}).items():
        if pkg in roles and o.get("role") in ROLES:
            roles[pkg] = o["role"]
    return roles


def family(name: str) -> str:
    """`Pricing13` → `Pricing`, `DiscountRuleV4` → `DiscountRule`, `pricing.py` → `pricing` (any source suffix)."""
    base = without_suffix(name).rstrip("$")
    return re.sub(r"(V?\d+|Params)+$", "", base) or base


def group_children(container: str, children: list[str], by_id: dict[str, dict],
                   method_count: dict[str, int], previous: list[dict] | None = None,
                   limit: int = GROUP_THRESHOLD) -> tuple[list[str], list[dict]]:
    """Collapse a crowded floor to at most GROUP_THRESHOLD items. Returns (items, groups); each group is
    {id, label, members, kind}. Order: data-only classes, the largest name families while still
    crowded, then range groups sized so everything fits (a range group's own floor is condensed again).
    Twins share the floor with the container's own children but never a group with them (see _twin_items)."""
    twins = sorted(c for c in children if c.startswith("twin:"))
    if twins and len(children) > limit:
        own = [c for c in children if not c.startswith("twin:")]
        twin_room = _twin_room(len(own), len(twins), limit)
        theirs = [g for g in previous or [] if all(m.startswith("twin:") for m in g["members"])]
        mine = [g for g in previous or [] if g not in theirs]
        t_items, t_groups = _twin_items(container, twins, by_id, theirs, twin_room)
        items, groups = (group_children(container, own, by_id, method_count, mine, limit=limit - len(t_items))
                         if own else ([], []))   # room the twins leave unused goes to the own children
        return items + t_items, groups + t_groups
    if twins:
        return sorted(c for c in children if not c.startswith("twin:")) + twins, []
    if len(children) <= limit:
        return sorted(children), []
    groups: list[dict] = []
    rest = sorted(children)
    data_only = [c for c in rest if by_id[c]["kind"] in ("class", "file") and method_count.get(c, 0) <= 1]
    if FAMILY_MIN <= len(data_only) < len(children):  # a group never holds the whole floor: grouping must shrink it
        groups.append({"id": f"grp:{container}:data-classes", "label": f"data ×{len(data_only)}",
                       "members": data_only, "kind": "data"})
        rest = [c for c in rest if c not in set(data_only)]
    fams: dict[str, list[str]] = {}
    for c in rest:
        fams.setdefault(family(by_id[c]["name"]), []).append(c)
    for fam, members in sorted(fams.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(rest) + len(groups) <= limit:
            break
        if len(members) < FAMILY_MIN or len(members) == len(children) or len(groups) + 1 >= limit:
            continue
        groups.append({"id": f"grp:{container}:fam:{fam}", "label": f"{fam} ×{len(members)}",
                       "members": members, "kind": "family"})
        rest = [c for c in rest if c not in set(members)]
    return _ranges(container, rest, groups, by_id, previous, limit)


def _twin_room(own: int, twins: int, limit: int) -> int:
    """How many of a crowded floor's items its twins get: all they need when they fit in half the floor, all
    the own children leave when those fit in half, else a share in proportion to their count."""
    if twins <= limit // 2 or not own:
        return min(twins, limit)
    if own <= limit // 2:
        return limit - own
    return min(limit - 1, max(1, round(limit * twins / (own + twins))))


def _twin_items(container: str, twins: list[str], by_id: dict[str, dict], previous: list[dict],
                room: int) -> tuple[list[str], list[dict]]:
    """A crowded floor's twins in `room` items. On a service or library floor, one `module` group per module
    with two or more twins (a twin stands for a module this service also deploys); otherwise, or when the
    modules alone overflow, name ranges as for any item. A module group's own floor is never folded again."""
    if len(twins) <= room:
        return twins, []
    if by_id.get(container, {}).get("kind") in ("service", "library"):
        mods: dict[str, list[str]] = {}
        for t in twins:
            mods.setdefault(by_id.get(t, {}).get("module") or "", []).append(t)
        loose = [t for m, ms in mods.items() if len(ms) < 2 or not m for t in ms]
        groups = [{"id": f"grp:{container}:module:{m}",
                   "label": f"{by_id[ms[0]].get('module_label') or m} ×{len(ms)}", "members": ms, "kind": "module"}
                  for m, ms in sorted(mods.items()) if len(ms) >= 2 and m]
        if groups and len(loose) + len(groups) <= room:
            return loose + [g["id"] for g in groups], groups
    return _ranges(container, twins, [], by_id, previous, room)


def _name(by_id: dict[str, dict], c: str) -> str:
    return by_id[c]["name"] if c in by_id else c


def _ranges(container: str, rest: list[str], groups: list[dict], by_id: dict[str, dict],
            previous: list[dict] | None, limit: int) -> tuple[list[str], list[dict]]:
    """`rest` beside `groups` in at most `limit` items: the overflow goes into name ranges."""
    groups = list(groups)
    sticky = (_sticky_ranges(rest, previous or [], by_id, limit - len(groups))
              if len(rest) + len(groups) > limit else None)   # a floor that shrank ungroups again
    if sticky is not None:   # the last map's range groups keep their ids and members; loose items stay loose
        grouped = {m for g in sticky for m in g["members"]}
        return [c for c in rest if c not in grouped] + [g["id"] for g in groups + sticky], groups + sticky
    if len(rest) + len(groups) > limit and len(rest) > max(1, limit - len(groups)):
        # group only the overflow, in ranges of at least RANGE_MIN: a floor just over the limit keeps most
        # items in view instead of hiding all of them in pairs; a lone item beside a floor that twins or groups
        # already fill stays loose
        n, free = len(rest), max(1, limit - len(groups))
        size = max(RANGE_MIN, -(-n // free))
        count = min(-(-(n - free) // (size - 1)), -(-n // size))
        tail = rest[n - min(n, count * size):]
        per = -(-len(tail) // count)
        chunks, rest = [tail[i:i + per] for i in range(0, len(tail), per)], rest[:n - len(tail)]
        for chunk in chunks:
            first, last = _name(by_id, chunk[0]), _name(by_id, chunk[-1])
            groups.append({"id": f"grp:{container}:range:{chunk[0]}", "label": f"{first} – {last} ×{len(chunk)}",
                           "members": chunk, "kind": "range"})
    return rest + [g["id"] for g in groups], groups


def _sticky_ranges(rest: list[str], previous: list[dict], by_id: dict[str, dict], slots: int) -> list[dict] | None:
    """Range groups rebuilt from the previous map: survivors stay in their group, items outside groups stay
    loose, and only as many loose items as the floor needs move into the group whose name range covers them
    (or the nearest). Returns the groups, or None to regroup fresh (nothing to keep, lopsided, or no fit)."""
    prev = [g for g in previous if g.get("kind") == "range"]
    if not prev or not rest:
        return None
    member = {m: g["id"] for g in prev for m in g["members"]}
    out: dict[str, list[str]] = {g["id"]: [c for c in rest if member.get(c) == g["id"]] for g in prev}
    out = {g: ms for g, ms in out.items() if ms}            # a group with no survivors goes
    if not out:
        return None
    name = lambda c: _name(by_id, c)  # noqa: E731
    loose = [c for c in rest if c not in member]
    overflow = len(loose) + len(out) - slots
    if overflow > 0:
        ranges = sorted((min(map(name, ms)), max(map(name, ms)), g) for g, ms in out.items())
        def home(c: str) -> tuple[int, str]:
            n = name(c)
            inside = next((g for lo, hi, g in ranges if lo <= n <= hi), None)
            return (0, inside) if inside else (1, next((g for lo, hi, g in reversed(ranges) if lo <= n), ranges[0][2]))
        for c in sorted(loose, key=lambda c: (home(c)[0], name(c)))[:overflow]:   # covered names move first
            out[home(c)[1]].append(c)
    groups = []
    for g in prev:
        members = sorted(out.get(g["id"], []))
        if members:
            first, last = name(members[0]), name(members[-1])
            groups.append({"id": g["id"], "label": f"{first} – {last} ×{len(members)}", "members": members,
                           "kind": "range"})
    still_loose = [c for c in rest if not any(c in g["members"] for g in groups)]
    fresh_size = max(RANGE_MIN, -(-len(rest) // max(1, slots)))
    fresh_count = -(-max(0, len(rest) - slots) // (fresh_size - 1))
    if (len(still_loose) + len(groups) > slots or max(len(g["members"]) for g in groups) > 2 * fresh_size
            or len(groups) > 2 * fresh_count + 1):
        return None   # lopsided, over-grouped (an older map's pairs) or no fit: regroup fresh rather than drift
    return groups
