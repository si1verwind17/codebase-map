"""Acceptances in OUT/map-notes.md: `- accept <check id> <floor code or *>  — <reason>`. Every other line is the
user's free text, read by the agent and ignored here."""
from __future__ import annotations

import re
from dataclasses import dataclass

KNOWN_CHECKS = ("lines.failed", "lines.plugged", "lines.trunks", "lines.under", "lines.mid-side", "lines.plate-wall",
                "lines.lane-drop", "lines.gap-stub", "lines.lane-gap", "text.cut", "text.over-line", "zone.narrow",
                "pads.corridor", "travel.long", "lost.relation", "floor.wide", "plan.crashed")
ACCEPT = re.compile(r"^\s*-\s*accept\b")
SEPS = ("—", "–", "--", "-")


@dataclass(frozen=True)
class Acceptance:
    check: str
    floor: str    # upper-cased floor code, or "*"
    reason: str
    line: int


def _parse(rest: str) -> tuple[str, str, str] | None:
    """(check, floor, reason) from what follows `accept`, or None."""
    words = rest.split(maxsplit=2)
    # a floor code never holds a dash: `S7—reason` is a separator glued to the floor, not a floor called that
    if len(words) < 2 or words[0] not in KNOWN_CHECKS or any(sep in words[1] for sep in SEPS):
        return None
    tail = words[2].strip() if len(words) > 2 else ""
    if not tail:
        return words[0], words[1], ""
    sep, *reason = tail.split(maxsplit=1)
    if sep not in SEPS:
        return None
    return words[0], words[1], reason[0].strip() if reason else ""


def parse_notes(text: str) -> tuple[list[Acceptance], list[tuple[int, str]]]:
    """(acceptances, not understood as (line number, line)). Line numbers count from 1."""
    accepted: list[Acceptance] = []
    bad: list[tuple[int, str]] = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not (m := ACCEPT.match(raw)):
            continue
        got = _parse(raw[m.end():])
        if got is None:
            bad.append((n, raw.strip()))
            continue
        check, floor, reason = got
        accepted.append(Acceptance(check, "*" if floor == "*" else floor.upper(), reason, n))
    return accepted, bad
