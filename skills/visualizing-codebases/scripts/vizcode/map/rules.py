"""Which meaning rules a map was made under, and what to re-check when the skill's rules have moved on.

CHANGES.md holds one `## Rules <N> — <date>` section per bump of RULES_VERSION (newest first); each `- ` line under
it is one re-check, pointing at the SKILL.md section that holds the rule. Section N lists what changed from N-1 to N.
The oldest section left is the floor: a map older than it cannot be given a list, only a full re-check."""
from __future__ import annotations

import re
from pathlib import Path

from .. import RULES_VERSION

CHANGES = Path(__file__).resolve().parent.parent.parent.parent / "CHANGES.md"
HEADING = re.compile(r"^## Rules (\d+) — \d{4}-\d{2}-\d{2}$")


def parse_changes(text: str) -> dict[int, list[str]]:
    """version -> its entry lines (without the `- `). ValueError on a malformed heading, a duplicate version, or
    versions that are not contiguous."""
    sections: dict[int, list[str]] = {}
    current: list[str] | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            m = HEADING.match(line)
            if not m:
                raise ValueError(f"CHANGES.md: malformed heading {line!r} (want '## Rules <N> — <YYYY-MM-DD>')")
            if int(m.group(1)) in sections:
                raise ValueError(f"CHANGES.md: duplicate section for rules {m.group(1)}")
            current = sections[int(m.group(1))] = []
        elif current is not None and line.startswith("- "):
            current.append(line[2:].strip())
    if sections and sorted(sections) != list(range(min(sections), max(sections) + 1)):
        raise ValueError(f"CHANGES.md: rule versions {sorted(sections)} are not contiguous")
    return sections


def map_rules(cmap: dict) -> int:
    """The rules version a map was made under; a map without the stamp predates it, so it counts as 1."""
    return cmap["meta"].get("rules_version", 1)


def behind(cmap: dict, changes_text: str) -> dict | None:
    """None when the map is current (or newer). Otherwise what to re-check: the entries of every section after the
    map's, oldest first, each prefixed `Rules <N>: `. When the map's next section was pruned (it is below the floor)
    there is no list: recheck is None and `floor` names the oldest section left."""
    v = map_rules(cmap)
    if v >= RULES_VERSION:
        return None
    sections = parse_changes(changes_text)
    if not sections:
        raise ValueError("CHANGES.md: no '## Rules <N>' sections")
    if RULES_VERSION not in sections:
        raise ValueError(f"CHANGES.md: no section for rules {RULES_VERSION} (RULES_VERSION was bumped without one)")
    floor = min(sections)
    if v + 1 < floor:
        return {"from": v, "to": RULES_VERSION, "recheck": None, "floor": floor}
    return {"from": v, "to": RULES_VERSION,
            "recheck": [f"Rules {n}: {e}" for n in range(v + 1, RULES_VERSION + 1) for e in sections[n]]}
