#!/usr/bin/env python3
"""Audit a written map: the drawing checks (viewer/dist/audit.mjs on Node 18+, optional), the content warnings and
the cycle finding, with the acceptances in OUT/map-notes.md applied. Writes OUT/audit.md and prints one summary line.

Usage: audit.py REPO [--out-dir docs/viz-code] [--full-audit]
The drawing checks stop at a budget (the largest floors first); --full-audit checks every floor, with a longer timeout.
Always exits 0: the map is already written, and nothing here may block it. VIZ_AUDIT=0 skips the drawing checks.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vizcode.map import findings, mapcheck  # noqa: E402
from vizcode import gitsrc, readme  # noqa: E402
from vizcode.map.notes import parse_notes  # noqa: E402

AUDIT_MJS = Path(__file__).resolve().parent.parent / "viewer" / "dist" / "audit.mjs"
SKIP = "drawing checks skipped: "
NO_NODE = SKIP + "Node not found (optional; install Node 18+ to check the drawing)"
MIN_NODE = 18
TIMEOUT = 150
FULL_TIMEOUT = 1800     # --full-audit: no budget, so a large map takes minutes
FULL = "--full-audit checks every floor"


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


def run_drawing(map_path: Path, node: str | None = None, timeout: float | None = None,
                full: bool = False) -> tuple[dict | None, str | None]:
    """(report, None) from audit.mjs, or (None, the reason the drawing checks were skipped). `full`: every floor, no
    budget."""
    timeout = timeout if timeout is not None else FULL_TIMEOUT if full else TIMEOUT
    exe = shutil.which(node or "node")
    if exe is None:
        return None, NO_NODE
    try:
        version = subprocess.run([exe, "--version"], capture_output=True, encoding="utf-8", errors="replace",
                                 timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None, NO_NODE
    m = re.match(r"v?(\d+)", version)
    if not m or int(m.group(1)) < MIN_NODE:
        return None, SKIP + f"Node {version or '(no version)'} is older than {MIN_NODE}"
    if not AUDIT_MJS.is_file():
        return None, SKIP + f"audit.mjs not found at {AUDIT_MJS}"
    try:
        done = subprocess.run([exe, str(AUDIT_MJS), str(map_path), *(["--full"] if full else [])], capture_output=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, SKIP + f"audit.mjs timed out after {timeout:g} s"
    except OSError as e:
        return None, SKIP + f"audit.mjs failed: {e}"
    if done.returncode != 0:
        return None, SKIP + f"audit.mjs failed: {_first_line(done.stderr) or f'exit {done.returncode}'}"
    lines = [ln for ln in done.stdout.splitlines() if ln.strip()]
    try:
        report = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        report = None
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        first = lines[0].strip() if lines else ""
        return None, SKIP + "audit.mjs printed no report" + (f": {first}" if first else "")
    return report, None


def _plural(n: int, word: str) -> str:
    if n != 1 and word.endswith("y"):
        return f"{n} {word[:-1]}ies"
    return f"{n} {word}{'' if n == 1 else 's'}"


def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _num(x) -> str:
    return f"{x:.2f}" if _is_num(x) else "?"


WORST = 5


def _measured(measured: dict) -> list[str]:
    """Each measure's worst floors: highest congestion, highest spread, least room between fit and switch zoom."""
    if not isinstance(measured, dict) or not measured:
        return []
    floors = [(str(c), m if isinstance(m, dict) else {}) for c, m in measured.items()]

    def spacing(m: dict) -> dict:
        return m.get("spacing") if isinstance(m.get("spacing"), dict) else {}

    def room(m: dict):
        f, s = m.get("fitZoom"), m.get("switchZoom")
        return f - s if _is_num(f) and _is_num(s) else None

    rows = [
        ("crowd.congestion", lambda m: m.get("congestion"), True,
         lambda c, m: f"{c} {_num(m.get('congestion'))}"),
        ("crowd.spacing", lambda m: spacing(m).get("spread"), True,
         lambda c, m: f"{c} area {_num(spacing(m).get('area'))} spread {_num(spacing(m).get('spread'))}"),
        ("fit.readable", room, False,
         lambda c, m: f"{c} fit {_num(m.get('fitZoom'))} vs switch {_num(m.get('switchZoom'))}"),
    ]
    out = []
    for name, key, high, show in rows:
        def rank(cm, key=key, high=high):   # floors without the number last
            v = key(cm[1])
            return (0, -v if high else v) if _is_num(v) else (1, 0)
        worst = sorted(floors, key=rank)   # stable: ties keep the report's order
        vals = [show(c, m) for c, m in worst[:WORST]]
        more = len(worst) - WORST
        out.append(f"- {name} — {', '.join(vals)}" + (f", … {more} more" if more > 0 else ""))
    return out


def _short(skip: str | None) -> str:
    """The reason the drawing checks were skipped, cut to its head: `Node not found`, `audit.mjs failed`."""
    return re.split(r" \(|: | at /", (skip or "").removeprefix(SKIP), maxsplit=1)[0].strip() or "skipped"


def render(report: dict | None, skip: str | None, warnings: list[dict], cycles: list[dict], notes: tuple,
           meta: dict) -> tuple[str, str]:
    """(audit.md text, summary line). meta: commit, date, out (as shown to the user), and optionally names
    (node id -> name) and relations (relation id -> label) for the findings."""
    acceptances, not_understood = notes
    errors = [w for w in warnings if w.get("id") == "audit.error"]
    warnings = [w for w in warnings if w.get("id") != "audit.error"]
    results = [x for x in (report or {}).get("results", []) if isinstance(x, dict)]
    skipped_codes = (report or {}).get("skippedCodes")
    if not isinstance(skipped_codes, list):
        skipped_codes = (report or {}).get("skipped")
    skipped_codes = [str(c) for c in skipped_codes] if isinstance(skipped_codes, list) else []
    failures = [r for r in results if not r.get("ok")]
    # a drawing check that threw is the audit's own bug, not a limit of this map: report it, never offer to accept it
    crashed = [r for r in failures if str(r.get("detail", "")).startswith("the check crashed")]
    failures = [r for r in failures if r not in crashed]
    crashed_keys = {(r.get("check"), str(r.get("code", "")).upper()) for r in crashed}
    errors += [{"id": "audit.error", "node": None,
                "detail": f"drawing check {r.get('check')} crashed on {r.get('code')}: "
                          f"{str(r.get('detail', '')).removeprefix('the check crashed: ')}"} for r in crashed]
    accepted: list[tuple[dict, object]] = []
    limits: list[dict] = []
    advisories: list[dict] = []   # failures of an advisory check (`advisory`): a known look, never a map limit
    used: set[int] = set()
    for f in failures:
        code = str(f.get("code", "")).upper()
        hit = next((a for a in acceptances if a.check == f.get("check") and a.floor in ("*", code)), None)
        if hit is None:
            (advisories if f.get("advisory") else limits).append(f)
        else:
            accepted.append((f, hit))
            used.update(a.line for a in acceptances if a.check == f.get("check") and a.floor in ("*", code))
    stale = []
    if report is not None:
        codes = {str(r.get("code", "")).upper() for r in results}
        maybe_unchecked = bool(skipped_codes)
        stale = [a for a in acceptances if a.line not in used
                 and not (maybe_unchecked and a.floor != "*" and a.floor not in codes)
                 and not any(a.check == c and a.floor in ("*", f) for c, f in crashed_keys)]   # left while it crashes

    out_md = f"{meta.get('out', 'docs/viz-code')}/audit.md"
    lines = [readme.header("audit.md"), "", f"# Map audit — {meta.get('commit', '?')} ({meta.get('date', '?')})"]
    if report is None:
        lines.append(f"Drawing checks: skipped — {(skip or '').removeprefix(SKIP)}")
    else:
        run = {r.get("check") for r in results} - {"plan.crashed"}
        checked = report.get("checked")
        lines.append(f"Drawing checks: {len(run)} run on {len(checked) if isinstance(checked, list) else 0} floors, "
                     f"{len(limits)} failed, {len(accepted)} accepted"
                     + (f", {_plural(len(advisories), 'advisory')}" if advisories else ""))
    lines.append(f"Content warnings: {len(warnings)}     Findings: {_plural(len(cycles), 'cycle')}"
                 + (f"     Audit errors: {len(errors)}" if errors else ""))

    def section(title: str, body: list[str]) -> None:
        if body:
            lines.extend(["", f"## {title}", *body])

    section("Map limits", [ln for f in limits for ln in (
        f"- {f.get('check')} · {f.get('code')} · row {f.get('row')} — {f.get('detail', '')}"
        + (f" at ({f['at'].get('x', '?')}, {f['at'].get('y', '?')})" if isinstance(f.get("at"), dict) else ""),
        f"  to accept: - accept {f.get('check')} {f.get('code')}")])
    section("Drawing advisories", [
        f"- {f.get('check')} · {f.get('code')} — {f.get('detail', '')}"
        + (f" at ({f['at'].get('x', '?')}, {f['at'].get('y', '?')})" if isinstance(f.get("at"), dict) else "")
        for f in advisories])
    section("Accepted", [f"- {f.get('check')} · {f.get('code')}" + (f' — "{a.reason}"' if a.reason else "")
                         for f, a in accepted])
    section("Stale acceptances", [f"- line {a.line}: accept {a.check} {a.floor} — matches no map limit or advisory"
                                  for a in stale])
    section("Notes not understood", [f"- line {n}: {text}" for n, text in not_understood])
    section("Audit errors", [f"- {w.get('detail', '')}" for w in errors])
    section("Content warnings", [f"- {w['id']} — {w['detail']}" for w in warnings])
    names = meta.get("names", {})
    rels = meta.get("relations", {})
    section("Findings", [
        "- cycle — " + " → ".join(names.get(s, s) for s in c["services"] + c["services"][:1])
        + f" ({'; '.join(rels.get(r, r) for r in c['relations'])})"
        + (f" (also in this group: {', '.join(names.get(s, s) for s in c['others'])})" if c.get("others") else "")
        for c in cycles])
    section("Measured (no threshold yet)", _measured((report or {}).get("measured") or {}))
    if report is not None and skipped_codes:
        section("Not checked", [f"- floors past the audit's budget: {', '.join(skipped_codes)}",
                                 f"- to check every floor: `audit.py REPO --out-dir {meta.get('out', 'docs/viz-code')}"
                                 " --full-audit` (no budget; slower)"])
    text = "\n".join(lines) + "\n"

    clean = (report is not None and not limits and not cycles and not warnings and not stale and not not_understood
             and not errors)
    budget = f" · {_plural(len(skipped_codes), 'floor')} not checked (audit budget; {FULL})" if skipped_codes else ""
    if clean:
        return text, "Map audit: no limits, no findings, no content warnings" + budget
    shown = f"not checked ({_short(skip)}; see {out_md})" if report is None else f"{len(limits)} (see {out_md})"
    return text, (f"Map limits: {shown} · findings: {_plural(len(cycles), 'cycle')} · "
                  f"content warnings: {len(warnings)}" + (f" · audit errors: {len(errors)}" if errors else "") + budget)


def audit_out(out: Path, shown_out: str, drawing: bool | None = None, full: bool = False) -> str:
    """Audit OUT/code-map.json, write OUT/audit.md; returns the summary line. drawing=None reads VIZ_AUDIT; `full`
    checks every floor (no budget). Never raises: the map is already written, so any failure here is one
    `map audit: failed: …` line."""
    try:
        return _audit_out(out, shown_out, drawing, full)
    except Exception as e:   # noqa: BLE001 — never block the caller
        return f"map audit: failed: {_first_line(f'{type(e).__name__}: {e}')}"


def _audit_out(out: Path, shown_out: str, drawing: bool | None, full: bool = False) -> str:
    map_path = out / "code-map.json"
    try:
        cmap = json.loads(map_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return f"map audit: {map_path} not found; run assemble.py first"
    except (OSError, ValueError) as e:
        return f"map audit: {map_path} unreadable: {e}"
    if drawing is None:
        drawing = os.environ.get("VIZ_AUDIT") != "0"
    report, skip = run_drawing(map_path, full=full) if drawing else (None, SKIP + "VIZ_AUDIT=0")

    def read(name: str) -> str | None:
        try:
            return (out / name).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            return None

    try:
        warnings = mapcheck.warnings(cmap, read("summary.md"))
        cycles = findings.cycles(cmap)
    except Exception as e:   # noqa: BLE001 — never block: a broken check is reported, not raised
        warnings = [{"id": "audit.error", "node": None, "detail": f"content checks failed: {e}"}]
        cycles = []
    notes = parse_notes(read("map-notes.md") or "")
    if not isinstance(cmap, dict):
        raise TypeError(f"code-map.json holds a {type(cmap).__name__}, not an object")
    meta = {"commit": str((cmap.get("meta") or {}).get("commit", "?"))[:12],
            "date": datetime.date.today().isoformat(), "out": shown_out,
            "names": {n["id"]: n.get("name") or n["id"] for n in cmap.get("nodes", []) if "id" in n},
            "relations": {r["id"]: f"{r.get('kind', '')} {r.get('key') or r['id']}".strip()
                          for r in cmap.get("relations", []) if "id" in r}}
    text, line = render(report, skip, warnings, cycles, notes, meta)
    try:
        (out / "audit.md").write_text(text, encoding="utf-8")
    except (OSError, ValueError) as e:
        line += f"  (audit.md not written: {e})"
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out-dir", default="docs/viz-code")
    ap.add_argument("--full-audit", action="store_true", help="check every floor's drawing, with no budget (slower)")
    a = ap.parse_args(argv)
    try:
        rel = gitsrc.rel_out_dir(a.repo, a.out_dir)
    except ValueError as e:
        print(f"map audit: {e}")
        return 0
    print(audit_out(a.repo / rel, rel, full=a.full_audit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
