#!/usr/bin/env python3
"""Plan an incremental rescan. Run extract.py first.

Usage: diff.py REPO [--out-dir docs/viz-code]
Writes stale.json (what to redo) and, unless a full rescan is needed,
meaning.json (every fact; stale ones carry "stale": true, examples included
when their fingerprint no longer matches). A full rescan removes meaning.json and
writes meaning.previous.json instead: the previous map's facts in the same shape, suspect ones flagged.
Either way stale.json lists the flagged facts, with `why` (fact id -> what it depends on that changed), and evidence on
unchanged lines follows them to their new place (`moved_evidence` counts them).
Prints the mode: none (no source change, nothing stale, no evidence moved) | rules | incremental | full.
When the map was made under older meaning rules (CHANGES.md), stale.json and the summary carry "rules": {from, to,
recheck}, the entries to re-check (a count in the summary; null when the map is older than the oldest entry, which
is a full rescan). An otherwise unchanged map then gets mode rules instead of none: meaning.json is written from the
map, the page and audit are not refreshed, and the agent re-checks the entries and assembles next.
On none it also rewrites the viewer page (view.py) and the audit (audit.py), so a current map shows the current
viewer and checks: the summary gains "refreshed", "page" and "audit", or "refresh_error" when the page could not be
written (still exit 0).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit  # noqa: E402
import view  # noqa: E402
from vizcode import gitsrc  # noqa: E402
from vizcode.map import rules  # noqa: E402
from vizcode.map.incremental import SOURCE_SUFFIXES, plan  # noqa: E402

PREVIOUS = "meaning.previous.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out-dir", default="docs/viz-code")
    a = ap.parse_args(argv)
    try:
        out_dir = gitsrc.rel_out_dir(a.repo, a.out_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = a.repo / out_dir
    cmap = json.loads((out / "code-map.json").read_text(encoding="utf-8"))
    structure = json.loads((out / "structure.json").read_text(encoding="utf-8"))
    report, meaning, previous = plan(a.repo, cmap, structure, out_dir)
    behind = rules.behind(cmap, rules.CHANGES.read_text(encoding="utf-8"))
    if behind:
        report["rules"] = behind
    if report["mode"] == "incremental" and not (
            report["stale_relations"] or report["stale_nodes"] or report["stale_examples"] or report["removed_nodes"]
            or report["moved_evidence"] or any(c["path"].endswith(SOURCE_SUFFIXES) for c in report["changed"])):
        report["mode"] = "rules" if behind else "none"
    previous_path = out / PREVIOUS
    if previous is not None:
        report["previous_meaning"] = PREVIOUS
        previous_path.write_text(json.dumps(previous, indent=1), encoding="utf-8")
    else:
        previous_path.unlink(missing_ok=True)
    (out / "stale.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    if meaning is not None:
        (out / "meaning.json").write_text(json.dumps(meaning, indent=1), encoding="utf-8")
    else:
        (out / "meaning.json").unlink(missing_ok=True)  # full rescan: meaning.json is rebuilt from meaning.previous.json
    summary = {"mode": report["mode"], "reason": report["reason"],
               "changed": len(report["changed"]), "stale_relations": len(report["stale_relations"]),
               "stale_nodes": len(report["stale_nodes"]), "stale_examples": len(report["stale_examples"]),
               "removed_nodes": len(report["removed_nodes"]), "moved_evidence": report["moved_evidence"]}
    if behind:
        summary["rules"] = {"from": behind["from"], "to": behind["to"],
                            "recheck": None if behind["recheck"] is None else len(behind["recheck"])}
    if previous is not None:
        summary["previous_meaning"] = PREVIOUS
        summary["previous_stale"] = (sum(1 for k in ("nodes", "relations") for x in previous[k] if x.get("stale"))
                                     + sum(1 for x in [*previous["examples"]["types"].values(),
                                                       *previous["examples"]["entries"]] if x.get("stale")))
    if report["mode"] == "none":
        try:
            summary["page"] = view.write_page(out)
            summary["refreshed"] = True
        except (OSError, ValueError) as e:   # the map is current: report the page, never fail the run for it
            summary["refreshed"] = False
            summary["refresh_error"] = str(e)
        summary["audit"] = audit.audit_out(out, str(out_dir))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
