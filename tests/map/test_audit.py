import json
import shutil
import stat
from pathlib import Path

import pytest

import audit
from vizcode import readme
from vizcode.notes import parse_notes

DEMO = Path(__file__).resolve().parents[2] / "demo/parking-city/docs/viz-code"
SKIP = "drawing checks skipped: "


@pytest.fixture(autouse=True)
def audit_on(monkeypatch):
    monkeypatch.delenv("VIZ_AUDIT", raising=False)


def stub(tmp_path, body, version="v20.11.0"):
    """A fake `node`: answers --version, otherwise runs `body`."""
    p = tmp_path / "bin" / "node"
    p.parent.mkdir(exist_ok=True)
    p.write_text(f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo {version}; exit 0; fi\n{body}\n')
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    return str(p)


def map_file(tmp_path):
    p = tmp_path / "code-map.json"
    p.write_text("{}")
    return p


def r(check, code, ok=False, detail="d", at=None):
    return {"check": check, "floor": f"id-{code}", "code": code, "row": "7", "ok": ok, "detail": detail,
            **({"at": at} if at else {})}


REPORT = {
    "checked": ["site", "id-S7", "id-S9"], "skipped": ["id-S12"], "skippedCodes": ["S12"],
    "results": [r("lines.failed", "site", ok=True),
                r("text.over-line", "S7", detail="`used by 10` badge over a belt", at={"x": 12, "y": 4}),
                r("lines.mid-side", "S9", detail="side door")],
    "measured": {"S7": {"congestion": 0.41, "spacing": {"area": 0.1, "spread": 0.3}, "fitZoom": 0.5,
                        "switchZoom": 0.6},
                 "S9": {"congestion": 0.22, "spacing": {"area": 0.2, "spread": 0.1}, "fitZoom": 0.7,
                        "switchZoom": 0.6}},
}


# --- run_drawing: every way Node can fail is a skip with its reason


def test_node_not_found(tmp_path):
    rep, skip = audit.run_drawing(map_file(tmp_path), node=str(tmp_path / "no-node"))
    assert rep is None
    assert skip == SKIP + "Node not found (optional; install Node 18+ to check the drawing)"


def test_node_too_old(tmp_path):
    rep, skip = audit.run_drawing(map_file(tmp_path), node=stub(tmp_path, "echo '{}'", version="v16.20.2"))
    assert rep is None and skip == SKIP + "Node v16.20.2 is older than 18"


def test_audit_mjs_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_MJS", tmp_path / "gone.mjs")
    rep, skip = audit.run_drawing(map_file(tmp_path), node=stub(tmp_path, "echo '{}'"))
    assert rep is None and skip == SKIP + f"audit.mjs not found at {tmp_path / 'gone.mjs'}"


def test_crash_reports_first_stderr_line(tmp_path):
    node = stub(tmp_path, "echo 'audit: cannot read the map: boom' >&2; echo second >&2; exit 2")
    rep, skip = audit.run_drawing(map_file(tmp_path), node=node)
    assert rep is None and skip == SKIP + "audit.mjs failed: audit: cannot read the map: boom"


def test_timeout(tmp_path):
    rep, skip = audit.run_drawing(map_file(tmp_path), node=stub(tmp_path, "exec sleep 5"), timeout=0.5)
    assert rep is None and skip == SKIP + "audit.mjs timed out after 0.5 s"


def test_full_audit_passes_full_and_waits_longer(tmp_path, monkeypatch):
    """--full-audit checks every floor (audit.mjs --full) with the longer timeout; the default keeps the budget."""
    seen = []
    monkeypatch.setattr(audit.subprocess, "run", lambda args, **kw: seen.append((args, kw.get("timeout")))
                        or audit.subprocess.CompletedProcess(args, 0, json.dumps(REPORT) if len(seen) > 1 else "v20.0.0", ""))
    node = stub(tmp_path, "true")
    for full in (False, True):
        seen.clear()
        assert audit.run_drawing(map_file(tmp_path), node=node, full=full) == (REPORT, None)
        args, timeout = seen[-1]
        assert (args[-1] == "--full") == full
        assert timeout == (audit.FULL_TIMEOUT if full else audit.TIMEOUT)
    assert audit.FULL_TIMEOUT > audit.TIMEOUT


def test_noise_before_the_json(tmp_path):
    node = stub(tmp_path, f"echo '(node:1) ExperimentalWarning: x' >&2; echo 'deprecated thing'; echo '';"
                          f" echo '{json.dumps(REPORT)}'; echo ''")
    rep, skip = audit.run_drawing(map_file(tmp_path), node=node)
    assert skip is None and rep == REPORT


def test_non_json_output(tmp_path):
    rep, skip = audit.run_drawing(map_file(tmp_path), node=stub(tmp_path, "echo 'not json at all'"))
    assert rep is None and skip == SKIP + "audit.mjs printed no report: not json at all"
    rep, skip = audit.run_drawing(map_file(tmp_path), node=stub(tmp_path, "true"))
    assert rep is None and skip == SKIP + "audit.mjs printed no report"


# --- render


META = {"commit": "68debe449cb6", "date": "2026-10-09", "out": "docs/viz-code"}


def test_render_limits_accepted_stale_and_the_rest():
    notes = parse_notes("- accept lines.mid-side s9 — the side door is on purpose, fine as is\n"
                        "- accept zone.narrow * -- stale one\n- accept nope S1\n")
    warns = [{"id": "ext.missing", "node": None, "detail": "config key PAYMENT_URL has no outside service"}]
    cyc = [{"services": ["svc:orders", "svc:billing"], "relations": ["r:a", "r:b"], "others": ["svc:shipping"]}]
    meta = {**META, "names": {"svc:orders": "orders", "svc:billing": "billing", "svc:shipping": "shipping"},
            "relations": {"r:a": "request POST /charge", "r:b": "request POST /orders/refund"}}
    text, line = audit.render(REPORT, None, warns, cyc, notes, meta)
    assert text.startswith(readme.header("audit.md") + "\n\n# Map audit — 68debe449cb6 (2026-10-09)\n")
    assert "Drawing checks: 3 run on 3 floors, 1 failed, 1 accepted\n" in text
    assert "Content warnings: 1     Findings: 1 cycle\n" in text
    limits = text.split("## Map limits\n")[1].split("\n## ")[0]
    assert limits == ("- text.over-line · S7 · row 7 — `used by 10` badge over a belt at (12, 4)\n"
                      "  to accept: - accept text.over-line S7\n")
    assert '## Accepted\n- lines.mid-side · S9 — "the side door is on purpose, fine as is"\n' in text
    assert "## Stale acceptances\n- line 2: accept zone.narrow * — matches no map limit or advisory\n" in text
    assert "## Notes not understood\n- line 3: - accept nope S1\n" in text
    assert "## Content warnings\n- ext.missing — config key PAYMENT_URL has no outside service\n" in text
    assert ("## Findings\n- cycle — orders → billing → orders (request POST /charge; request POST /orders/refund)"
            " (also in this group: shipping)\n" in text)
    assert "- crowd.congestion — S7 0.41, S9 0.22\n" in text
    assert "- crowd.spacing — S7 area 0.10 spread 0.30, S9 area 0.20 spread 0.10\n" in text
    assert "- fit.readable — S7 fit 0.50 vs switch 0.60, S9 fit 0.70 vs switch 0.60\n" in text
    assert ("## Not checked\n- floors past the audit's budget: S12\n"
            "- to check every floor: `audit.py REPO --out-dir docs/viz-code --full-audit` (no budget; slower)\n") in text
    assert line == ("Map limits: 1 (see docs/viz-code/audit.md) · findings: 1 cycle · content warnings: 1"
                    " · 1 floor not checked (audit budget; --full-audit checks every floor)")


def test_render_clean_but_budgeted_says_floors_were_skipped():
    rep = {**REPORT, "results": [r("lines.failed", "site", ok=True)], "measured": {},
           "skipped": ["id-S12", "id-S13"], "skippedCodes": ["S12", "S13"]}
    _, line = audit.render(rep, None, [], [], ([], []), META)
    assert line == ("Map audit: no limits, no findings, no content warnings"
                    " · 2 floors not checked (audit budget; --full-audit checks every floor)")


def test_render_all_pass_leaves_out_empty_sections():
    rep = {**REPORT, "skipped": [], "skippedCodes": [], "results": [r("lines.failed", "site", ok=True)], "measured": {}}
    text, line = audit.render(rep, None, [], [], ([], []), META)
    assert line == "Map audit: no limits, no findings, no content warnings"
    assert "Drawing checks: 1 run on 3 floors, 0 failed, 0 accepted" in text
    for head in ("Map limits", "Accepted", "Stale", "not understood", "Content warnings\n", "Findings\n",
                 "Measured", "Not checked"):
        assert f"## {head}" not in text


def test_render_skipped_calls_nothing_stale():
    notes = parse_notes("- accept zone.narrow S1\n")
    text, line = audit.render(None, SKIP + "Node not found (x)", [], [], notes, META)
    assert "Drawing checks: skipped — Node not found (x)\n" in text
    assert "Stale" not in text and "## Accepted" not in text
    assert line == ("Map limits: not checked (Node not found; see docs/viz-code/audit.md) · findings: 0 cycles · "
                    "content warnings: 0")


def test_plan_crashed_is_a_limit():
    rep = {**REPORT, "skipped": [], "skippedCodes": [], "results": [r("plan.crashed", "S4", detail="boom")]}
    text, line = audit.render(rep, None, [], [], ([], []), META)
    assert "- plan.crashed · S4 · row 7 — boom\n  to accept: - accept plan.crashed S4\n" in text
    assert line.startswith("Map limits: 1 ")


def test_an_advisory_is_listed_not_counted():
    """A failed advisory check (`advisory`: flights.hidden, a known look) goes under Drawing advisories: no map limit,
    no change to the summary line; an acceptance of it still moves it to Accepted."""
    detail = "produce a|b passes under svc:billing for 126 px"
    adv = {**r("flights.hidden", "site", detail=detail, at={"x": 4, "y": 9}), "advisory": True}
    rep = {**REPORT, "skipped": [], "skippedCodes": [], "results": [r("lines.failed", "site", ok=True), adv],
           "measured": {}}
    text, line = audit.render(rep, None, [], [], ([], []), META)
    assert line == "Map audit: no limits, no findings, no content warnings"
    assert "Drawing checks: 2 run on 3 floors, 0 failed, 0 accepted, 1 advisory\n" in text
    assert ("## Drawing advisories\n- flights.hidden · site — produce a|b passes under svc:billing for 126 px at (4, 9)\n"
            in text)
    assert "## Map limits" not in text and "to accept" not in text
    two = {**rep, "results": [adv, {**adv, "code": "S2", "floor": "id-S2"}]}
    assert ", 2 advisories\n" in audit.render(two, None, [], [], ([], []), META)[0]
    text, line = audit.render(rep, None, [], [], parse_notes("- accept flights.hidden *\n"), META)
    assert "## Drawing advisories" not in text and "## Accepted\n- flights.hidden · site\n" in text
    assert "Stale" not in text and line == "Map audit: no limits, no findings, no content warnings"


# --- main: always exit 0, writes OUT/audit.md


def out_repo(tmp_path, name="repo", out="docs/viz-code"):
    repo = tmp_path / name
    o = repo / out
    o.mkdir(parents=True)
    shutil.copyfile(DEMO / "code-map.json", o / "code-map.json")
    return repo, o


def test_main_missing_map_exits_0(tmp_path, capsys):
    (tmp_path / "repo").mkdir()
    assert audit.main([str(tmp_path / "repo")]) == 0
    assert "code-map.json" in capsys.readouterr().out


def test_main_bad_out_dir_exits_0(tmp_path, capsys):
    (tmp_path / "repo").mkdir()
    assert audit.main([str(tmp_path / "repo"), "--out-dir", "/etc"]) == 0


@pytest.mark.parametrize("body, drew", [("echo boom >&2; exit 2", False), ("echo 'not json'", False),
                                        (f"echo '{json.dumps(REPORT)}'", True)])
def test_main_every_path_exits_0_with_spaces_and_odd_out(tmp_path, monkeypatch, capsys, body, drew):
    node = stub(tmp_path, body)
    monkeypatch.setenv("PATH", f"{Path(node).parent}:/usr/bin:/bin")
    repo, o = out_repo(tmp_path, "my repo", "maps/the map")
    (o / "map-notes.md").write_text("- accept lines.mid-side S9 — fine\r\n- accept bogus\r\n")
    assert audit.main([str(repo), "--out-dir", "maps/the map"]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    text = (o / "audit.md").read_text()
    commit = json.loads((DEMO / "code-map.json").read_text())["meta"]["commit"][:12]
    assert text.startswith(readme.header("audit.md") + "\n\n")
    assert f"\n# Map audit — {commit} (" in text
    assert "## Notes not understood\n- line 2: - accept bogus\n" in text
    assert "see maps/the map/audit.md)" in line
    if drew:
        assert "Drawing checks: 3 run on 3 floors" in text
    else:
        assert "Drawing checks: skipped — audit.mjs" in text


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_real_node_on_the_demo(tmp_path, capsys):
    repo, o = out_repo(tmp_path)
    assert audit.main([str(repo)]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    text = (o / "audit.md").read_text()
    assert "Drawing checks: 20 run on " in text
    # the counts follow the demo's map-notes and the checks; only the shape is pinned here
    assert line.startswith("Map ")
    if line.startswith("Map audit: no limits"):
        assert "## Map limits" not in text
    else:
        assert line.startswith("Map limits: ") and "(see docs/viz-code/audit.md) · findings: " in line


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_real_node_full_audit_checks_every_floor(tmp_path, capsys):
    repo, o = out_repo(tmp_path)
    floors = len(json.loads((o / "code-map.json").read_text())["layout"]["containers"])
    assert audit.main([str(repo), "--full-audit"]) == 0
    text = (o / "audit.md").read_text()
    assert f" run on {floors} floors" in text and "## Not checked" not in text
    assert "not checked (audit budget" not in capsys.readouterr().out


def test_viz_audit_0_skips_the_drawing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIZ_AUDIT", "0")
    repo, o = out_repo(tmp_path)
    assert audit.main([str(repo)]) == 0
    assert "Drawing checks: skipped — VIZ_AUDIT=0" in (o / "audit.md").read_text()


# --- never block: anything odd in the map or the report still writes audit.md or prints the failed line


def _ran(repo, capsys):
    assert audit.main([str(repo)]) == 0
    line = capsys.readouterr().out.strip().splitlines()[-1]
    o = repo / "docs/viz-code"
    return line, (o / "audit.md").read_text() if (o / "audit.md").exists() else None


def test_a_list_map_prints_the_failed_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIZ_AUDIT", "0")
    repo, o = out_repo(tmp_path)
    (o / "code-map.json").write_text("[]")
    line, text = _ran(repo, capsys)
    assert line.startswith("map audit: failed: ") or text is not None
    assert "\n" not in line


def test_null_meta_still_writes(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIZ_AUDIT", "0")
    repo, o = out_repo(tmp_path)
    m = json.loads((o / "code-map.json").read_text())
    m["meta"] = None
    (o / "code-map.json").write_text(json.dumps(m))
    line, text = _ran(repo, capsys)
    assert text is not None and "\n# Map audit — ? (" in text


@pytest.mark.parametrize("change", [
    {"results": [r("text.cut", "S7", at={"y": 4})]},
    {"skipped": [3, None, {"x": 1}], "skippedCodes": [3, None]},
    {"measured": {"S7": {"congestion": "lots", "spacing": None}, "S8": None}},
])
def test_odd_reports_still_write(tmp_path, monkeypatch, capsys, change):
    node = stub(tmp_path, f"echo '{json.dumps({**REPORT, **change})}'")
    monkeypatch.setenv("PATH", f"{Path(node).parent}:/usr/bin:/bin")
    repo, o = out_repo(tmp_path)
    line, text = _ran(repo, capsys)
    assert not line.startswith("map audit: failed"), line
    assert text is not None and "Drawing checks: " in text


def test_any_exception_is_one_failed_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("VIZ_AUDIT", "0")
    repo, o = out_repo(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("render broke\nsecond line")
    monkeypatch.setattr(audit, "render", boom)
    line, _ = _ran(repo, capsys)
    assert line == "map audit: failed: RuntimeError: render broke"


def test_bad_bytes_from_node_are_replaced(tmp_path):
    node = stub(tmp_path, r"printf 'bad \377 byte\n' >&2; exit 2")
    rep, skip = audit.run_drawing(map_file(tmp_path), node=node)
    assert rep is None and skip == SKIP + "audit.mjs failed: bad � byte"


# --- the measured section, the skipped reason, audit errors


def test_measured_shows_the_worst_five_per_measure():
    m = {f"F{i}": {"congestion": i / 10, "spacing": {"area": 0.1, "spread": (7 - i) / 10},
                   "fitZoom": 0.5 + i / 100, "switchZoom": 0.6} for i in range(1, 8)}
    m["F0"] = {"congestion": None}
    text, _ = audit.render({**REPORT, "skipped": [], "skippedCodes": [], "measured": m}, None, [], [], ([], []), META)
    assert "- crowd.congestion — F7 0.70, F6 0.60, F5 0.50, F4 0.40, F3 0.30, … 3 more\n" in text
    assert ("- crowd.spacing — F1 area 0.10 spread 0.60, F2 area 0.10 spread 0.50, F3 area 0.10 spread 0.40, "
            "F4 area 0.10 spread 0.30, F5 area 0.10 spread 0.20, … 3 more\n") in text
    assert ("- fit.readable — F1 fit 0.51 vs switch 0.60, F2 fit 0.52 vs switch 0.60, F3 fit 0.53 vs switch 0.60, "
            "F4 fit 0.54 vs switch 0.60, F5 fit 0.55 vs switch 0.60, … 3 more\n") in text


@pytest.mark.parametrize("skip, short", [
    (audit.NO_NODE, "Node not found"),
    (SKIP + "Node v16.20.2 is older than 18", "Node v16.20.2 is older than 18"),
    (SKIP + "audit.mjs not found at /x/y/audit.mjs", "audit.mjs not found"),
    (SKIP + "audit.mjs failed: boom: bang", "audit.mjs failed"),
    (SKIP + "audit.mjs timed out after 60 s", "audit.mjs timed out after 60 s"),
    (SKIP + "audit.mjs printed no report: junk", "audit.mjs printed no report"),
    (SKIP + "VIZ_AUDIT=0", "VIZ_AUDIT=0"),
])
def test_skipped_line_names_the_short_reason(skip, short):
    _, line = audit.render(None, skip, [], [], ([], []), META)
    assert line.startswith(f"Map limits: not checked ({short}; see docs/viz-code/audit.md) · ")


def test_audit_error_is_not_a_content_warning():
    rep = {**REPORT, "skipped": [], "skippedCodes": [], "results": [r("lines.failed", "site", ok=True)], "measured": {}}
    errs = [{"id": "audit.error", "node": None, "detail": "content checks failed: boom"}]
    text, line = audit.render(rep, None, errs, [], ([], []), META)
    assert "Content warnings: 0     Findings: 0 cycles     Audit errors: 1\n" in text
    assert "## Audit errors\n- content checks failed: boom\n" in text
    assert "## Content warnings" not in text
    assert line == ("Map limits: 0 (see docs/viz-code/audit.md) · findings: 0 cycles · content warnings: 0 · "
                    "audit errors: 1")


def test_a_crashed_drawing_check_is_an_audit_error_not_a_map_limit():
    rep = {"checked": ["S3"], "skipped": [], "results": [
        {"check": "lines.trunks", "floor": "S3", "code": "S3·P1", "row": "9", "ok": False,
         "detail": "the check crashed: Cannot read properties of undefined (reading '0')"}]}
    text, line = audit.render(rep, None, [], [], ([], []), META)
    assert "## Map limits" not in text and "to accept" not in text
    assert "lines.trunks crashed on S3·P1" in text and "audit errors: 1" in line


def test_an_acceptance_for_a_crashing_check_is_not_stale():
    from vizcode import notes
    rep = {"checked": ["S3"], "skipped": [], "results": [
        {"check": "lines.trunks", "floor": "S3", "code": "S3·P1", "row": "9", "ok": False,
         "detail": "the check crashed: boom"}]}
    accepted = notes.parse_notes("- accept lines.trunks S3·P1 — known\n")
    text, _ = audit.render(rep, None, [], [], accepted, META)
    assert "Stale" not in text
