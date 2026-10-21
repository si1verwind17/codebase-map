import re
from pathlib import Path

import pytest

from vizcode.notes import KNOWN_CHECKS, Acceptance, parse_notes


def one(text):
    acc, bad = parse_notes(text)
    assert bad == []
    assert len(acc) == 1
    return acc[0]


def test_canonical_form():
    a = one("# notes\n- accept lines.mid-side S9  — the side door is on purpose, fine as is\n")
    assert a == Acceptance("lines.mid-side", "S9", "the side door is on purpose, fine as is", 2)


@pytest.mark.parametrize("sep", ["—", "–", "--", "-"])
def test_every_separator(sep):
    assert one(f"- accept text.cut S7·P1 {sep} long names\n") == Acceptance("text.cut", "S7·P1", "long names", 1)


def test_crlf_and_extra_spaces():
    text = "free text\r\n  -   accept   text.over-line    S7   —   badge  on a belt \r\n"
    assert one(text) == Acceptance("text.over-line", "S7", "badge  on a belt", 2)


def test_lower_case_floor_and_star():
    assert one("- accept zone.narrow s9·p1 — fine").floor == "S9·P1"
    assert one("- accept travel.long *").floor == "*"


def test_no_reason():
    assert one("- accept lines.trunks S2") == Acceptance("lines.trunks", "S2", "", 1)


def test_plan_crashed_is_known():
    assert "plan.crashed" in KNOWN_CHECKS and len(KNOWN_CHECKS) == 17
    assert one("- accept plan.crashed S4").check == "plan.crashed"


def test_known_checks_are_the_viewer_audit_checks():
    """A drawing check the viewer runs can be accepted in map-notes.md: the two lists name the same checks."""
    src = (Path(__file__).parents[2] / "viewer/src/audit/types.ts").read_text()
    union = re.search(r"export type CheckId =([^;]+);", src).group(1)
    assert set(re.findall(r'"([a-z.-]+)"', union)) == set(KNOWN_CHECKS)
    assert one("- accept floor.wide S7 — a wide floor is fine here").check == "floor.wide"


def test_unknown_check_and_missing_floor_are_not_understood():
    text = "- accept lines.wobbly S1 — x\n\n- accept text.cut\n- accept\n- accept text.cut — no floor\n"
    acc, bad = parse_notes(text)
    assert acc == []
    assert [n for n, _ in bad] == [1, 3, 4, 5]
    assert bad[0][1] == "- accept lines.wobbly S1 — x"


def test_free_text_bullets_are_ignored():
    acc, bad = parse_notes("- billing is a service\n- acceptance tests live in it/\n* accept text.cut S1\n"
                           "- accepted: text.cut S1\n")
    assert acc == [] and bad == []


@pytest.mark.parametrize("sep", ["—", "–", "--", "-"])
def test_separator_glued_to_the_floor_is_not_understood(sep):
    acc, bad = parse_notes(f"- accept text.cut S7{sep}reason here\n- accept text.cut S7{sep}\n")
    assert acc == []
    assert [n for n, _ in bad] == [1, 2]
