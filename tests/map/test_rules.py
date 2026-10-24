import json

import pytest

import assemble as assemble_cli
import diff as diff_cli
import extract
from conftest import commit_all, write_files
from meaning_fixture import MEANING
from helpers import OUT, scan
from vizcode import mapcheck, rules
from vizcode import RULES_VERSION

TEXT = """# Meaning-rules changes

intro line

## Rules 3 — 2026-10-13
- third a
- third b

## Rules 2 — 2026-10-12
- second a

## Rules 1 — 2026-10-11
- Baseline: nothing to re-check.
"""


def cmap_at(v):
    return {"meta": {} if v is None else {"rules_version": v}}


def test_parse_collects_entries_until_next_heading():
    assert rules.parse_changes(TEXT) == {3: ["third a", "third b"], 2: ["second a"],
                                         1: ["Baseline: nothing to re-check."]}


@pytest.mark.parametrize("text", [
    "## Rules x — 2026-10-11\n- a\n",
    "## Rules 1 - 2026-10-11\n- a\n",
    "## Rules 1 — 2026-10-11\n- a\n\n## Rules 1 — 2026-10-12\n- b\n",
    "## Rules 3 — 2026-10-11\n- a\n\n## Rules 1 — 2026-10-10\n- b\n",
])
def test_parse_rejects_malformed(text):
    with pytest.raises(ValueError):
        rules.parse_changes(text)


def test_real_changes_file_matches_the_version():
    parsed = rules.parse_changes(rules.CHANGES.read_text())
    assert max(parsed) == RULES_VERSION
    assert sorted(parsed) == list(range(min(parsed), RULES_VERSION + 1))


def test_map_without_the_field_counts_as_one():
    assert rules.map_rules(cmap_at(None)) == 1 and rules.map_rules(cmap_at(4)) == 4


def test_behind_lists_newer_entries_oldest_first(monkeypatch):
    monkeypatch.setattr(rules, "RULES_VERSION", 3)
    assert rules.behind(cmap_at(3), TEXT) is None
    assert rules.behind(cmap_at(5), TEXT) is None
    assert rules.behind(cmap_at(1), TEXT) == {
        "from": 1, "to": 3, "recheck": ["Rules 2: second a", "Rules 3: third a", "Rules 3: third b"]}


def test_behind_the_floor_asks_for_a_full_recheck(monkeypatch):
    monkeypatch.setattr(rules, "RULES_VERSION", 3)
    pruned = TEXT.split("## Rules 2")[0]
    assert rules.behind(cmap_at(1), pruned) == {"from": 1, "to": 3, "recheck": None, "floor": 3}
    assert rules.behind(cmap_at(2), pruned)["recheck"] == ["Rules 3: third a", "Rules 3: third b"]


def run_diff(repo, monkeypatch, version, text):
    monkeypatch.setattr(rules, "RULES_VERSION", version)
    monkeypatch.setattr(rules, "CHANGES", type("P", (), {"read_text": lambda self, **kw: text})())
    extract.main([str(repo)])
    diff_cli.main([str(repo)])
    out = repo.joinpath(*OUT)
    return json.loads((out / "stale.json").read_text()), out


def scan_at_rules_one(repo):
    """Scan, then restamp the committed map as made under rules 1."""
    scan(repo)
    path = repo.joinpath(*OUT, "code-map.json")
    cmap = json.loads(path.read_text())
    cmap["meta"]["rules_version"] = 1
    path.write_text(json.dumps(cmap))
    return commit_all(repo, "map at rules 1")


def test_unchanged_map_behind_the_rules_gets_mode_rules(shop_repo, monkeypatch, capsys):
    scan_at_rules_one(shop_repo)
    capsys.readouterr()
    stale, out = run_diff(shop_repo, monkeypatch, 3, TEXT)
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert stale["mode"] == "rules" and stale["rules"]["from"] == 1
    assert summary["mode"] == "rules" and summary["rules"] == {"from": 1, "to": 3, "recheck": 3}
    assert "page" not in summary and "audit" not in summary
    assert (out / "meaning.json").exists()


def test_current_map_stays_none(shop_repo, monkeypatch, capsys):
    scan(shop_repo)
    stale, _ = run_diff(shop_repo, monkeypatch, rules.RULES_VERSION, TEXT.split("## Rules 3")[0] + "## Rules 1 — 2026-10-11\n- b\n")
    assert stale["mode"] == "none" and "rules" not in stale


def test_incremental_carries_rules(shop_repo, monkeypatch):
    scan_at_rules_one(shop_repo)
    write_files(shop_repo, {"worker/main.py": (shop_repo / "worker/main.py").read_text() + "\n# touched\n"})
    commit_all(shop_repo, "touch worker")
    stale, _ = run_diff(shop_repo, monkeypatch, 3, TEXT)
    assert stale["mode"] == "incremental" and stale["rules"]["recheck"][0] == "Rules 2: second a"


def test_map_below_the_floor_forces_full(shop_repo, monkeypatch, capsys):
    scan_at_rules_one(shop_repo)
    capsys.readouterr()
    stale, out = run_diff(shop_repo, monkeypatch, 3, TEXT.split("## Rules 2")[0])
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert stale["mode"] == "full" and "older than the oldest entry in CHANGES.md (3)" in stale["reason"]
    assert summary["rules"] == {"from": 1, "to": 3, "recheck": None}
    previous = json.loads((out / "meaning.previous.json").read_text())   # code unchanged, yet facts are flagged
    assert any(x.get("stale") for k in ("nodes", "relations") for x in previous[k])


def test_assemble_stamps_rules_version(shop_repo):
    scan(shop_repo)
    cmap = json.loads(shop_repo.joinpath(*OUT, "code-map.json").read_text())
    assert cmap["meta"]["rules_version"] == RULES_VERSION


def test_schema_accepts_a_map_without_the_field(shop_repo):
    import jsonschema
    scan(shop_repo)
    path = shop_repo.joinpath(*OUT, "code-map.json")
    cmap = json.loads(path.read_text())
    del cmap["meta"]["rules_version"]
    jsonschema.validate(cmap, mapcheck.SCHEMA)


def test_behind_explains_a_changes_file_that_does_not_match(monkeypatch):
    monkeypatch.setattr(rules, "RULES_VERSION", 3)
    with pytest.raises(ValueError, match="no '## Rules"):
        rules.behind(cmap_at(1), "# Meaning-rules changes\n")
    with pytest.raises(ValueError, match="no section for rules 3"):
        rules.behind(cmap_at(1), TEXT.split("## Rules 2")[0].replace("Rules 3", "Rules 2"))


def test_rules_two_to_eight_follow_the_baseline():
    assert RULES_VERSION == 8
    parsed = rules.parse_changes(rules.CHANGES.read_text(encoding="utf-8"))
    assert parsed[1] == ["Baseline: nothing to re-check."]
    assert len(parsed[2]) == 2 and parsed[2][0].startswith("In-process queues (SKILL.md § In-process queues)")
    assert parsed[2][1].startswith("Actor and entity messages")
    assert len(parsed[3]) == 1 and parsed[3][0].startswith("A call's direction (SKILL.md § data)")
    assert len(parsed[4]) == 4 and parsed[4][0].startswith("Route keys (SKILL.md § Stack)")
    assert parsed[4][1].startswith("Route handlers (SKILL.md step 5)")
    assert parsed[4][2].startswith("Deployables (SKILL.md § Deployables, not folders)")
    assert parsed[4][3].startswith("Queues in a store or a job system")
    assert len(parsed[5]) == 2 and parsed[5][0].startswith("Job triggers (SKILL.md")
    assert parsed[5][1].startswith("Generic jobs (SKILL.md § Matching interactions)")
    assert [x.split(" (")[0] for x in parsed[6]] == ["Tables by naming default", "Framework-implemented interfaces",
                                                    "Base paths", "Route styles"]
    assert [x.split(" (")[0] for x in parsed[7]] == ["Outbound requests", "SQL kept outside the code", "Inline handlers"]
    assert [x.split(" (")[0] for x in parsed[8]] == ["FastAPI prefixes", "Flask routes", "Request objects",
                                                    "Job systems", "Roles of one module", "Deployables"]


def test_a_map_at_rules_one_gets_the_queue_recheck(shop_repo):
    scan_at_rules_one(shop_repo)
    extract.main([str(shop_repo)])
    diff_cli.main([str(shop_repo)])
    stale = json.loads(shop_repo.joinpath(*OUT, "stale.json").read_text())
    assert stale["mode"] == "rules" and stale["rules"]["recheck"][0].startswith("Rules 2: In-process queues")
