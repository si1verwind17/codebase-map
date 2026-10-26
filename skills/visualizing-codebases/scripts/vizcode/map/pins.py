"""Pinned traces (SKILL.md § Pinned traces, format.md § Pins): the shape checks assemble.py makes on `pins` and
`unpinned` in meaning.json before assembling, and the id rule."""
from __future__ import annotations

import re

DIRECTIONS = ("downstream", "upstream", "both")
BY = ("agent", "user")
FIELDS = ("id", "title", "start", "direction", "by")


def slug(title: str) -> str:
    """A pin's id from its title: its lower-case letters and digits in runs, joined by `-`
    (`Driver reserves a bay, billing charges it` -> `driver-reserves-a-bay-billing-charges-it`); `pin` when it has none."""
    return "-".join(re.findall(r"[a-z0-9]+", title.lower())) or "pin"


def errors(meaning: dict) -> list[str]:
    """Problems with `pins` and `unpinned`, as a fix list. Both must already be lists (meaning_errors checks that).
    A pin's `start` is not checked here: a start missing from the map is listed by the audit, not refused."""
    out: list[str] = []
    unpinned = meaning.get("unpinned") or []
    for i, u in enumerate(unpinned, 1):
        if not isinstance(u, str) or not u:
            out.append(f"unpinned {i}: must be a pin id (a string)")
    retired = {u for u in unpinned if isinstance(u, str)}
    seen: dict[str, int] = {}
    for i, p in enumerate(meaning.get("pins") or [], 1):
        if not isinstance(p, dict):
            out.append(f"pin {i}: must be an object {{id, title, start, direction, by}}")
            continue
        missing = [k for k in FIELDS if not isinstance(p.get(k), str) or not p[k]]
        if missing:
            out.append(f"pin {i}: missing {', '.join(missing)}")
            continue
        pid = p["id"]
        if not re.fullmatch(re.escape(slug(p["title"])) + r"(?:-[2-9]|-[1-9][0-9]+)?", pid):
            out.append(f"pin {pid}: id is not the slug of its title — use {slug(p['title'])!r} "
                       "(add -2, -3 when it is taken)")
        if p["direction"] not in DIRECTIONS:
            out.append(f"pin {pid}: direction {p['direction']!r} is not one of {', '.join(DIRECTIONS)}")
        if p["by"] not in BY:
            out.append(f"pin {pid}: by {p['by']!r} is not agent or user")
        if pid in seen:
            out.append(f"pin {pid}: duplicate id (pins {seen[pid]} and {i}) — give the later one the next free "
                       "suffix (-2, -3)")
        seen.setdefault(pid, i)
        if pid in retired:
            out.append(f"pin {pid}: the id is in unpinned (the user removed that pin) — never pin it again: delete "
                       "this pin, or give a new user pin the next free suffix (-2, -3)")
    return out


TRACE_START_KINDS = ("method", "table", "topic", "in-process-queue", "external", "datastore",
                     "service", "library", "package", "file", "class")


def start_errors(cmap: dict) -> list[str]:
    """Pins of an assembled map whose `start` is in the map with a kind the viewer cannot trace from, as a fix list.
    Every node kind of format.md can be traced (a service, library, package, file or class from the seeds inside it:
    examples.seeds). A start missing from the map is not refused: the audit lists it (`pin.start-missing`)."""
    kinds = {n["id"]: n.get("kind") for n in cmap.get("nodes", [])}
    return [f"pin {p.get('id')}: start {p['start']} is a {kinds[p['start']]}, which the viewer cannot trace from — "
            "start at a method, table, topic, in-process-queue, external, datastore, service, library, package, file or class"
            for p in cmap.get("pins", []) if p.get("start") in kinds and kinds[p["start"]] not in TRACE_START_KINDS]
