#!/usr/bin/env python3
"""Merge structure.json and the agent's meaning.json into a validated code-map.json, and write index.html
(the viewer with the map built in) beside it.

Usage: assemble.py REPO [--out-dir docs/viz-code] [--relayout] [--full-audit]
Exit 1 (and write code-map.invalid.json) when the map fails validation; exit 3 when the map is valid
but the viewer page could not be written. On exit 0 it then runs audit.py (VIZ_AUDIT=0 skips its drawing checks)
and prints the audit's summary line last (--full-audit: the drawing checks on every floor, no budget).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import audit  # noqa: E402
import view  # noqa: E402
from vizcode import gitsrc, mapcheck  # noqa: E402
from vizcode.assemble import assemble, ensure_repo_files, meaning_errors  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out-dir", default="docs/viz-code")
    ap.add_argument("--relayout", action="store_true", help="place every item afresh instead of keeping positions")
    ap.add_argument("--full-audit", action="store_true", help="check every floor's drawing, with no budget (slower)")
    a = ap.parse_args(argv)
    try:
        out_dir = gitsrc.rel_out_dir(a.repo, a.out_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = a.repo / out_dir
    structure = json.loads((out / "structure.json").read_text(encoding="utf-8"))
    head = gitsrc.head_commit(a.repo)
    if head != structure["meta"]["commit"]:
        print(f"HEAD moved since extract.py (structure at {structure['meta']['commit'][:12]}, HEAD at {head[:12]}): "
              "rerun extract.py (and diff.py if a map exists), then re-check the meaning pass against the new commit",
              file=sys.stderr)
        return 1
    meaning_path = out / "meaning.json"
    if not meaning_path.exists() and (out / "meaning.previous.json").exists():
        print("a full rescan waits: copy meaning.previous.json to meaning.json, resolve its `stale` flags, then "
              "assemble (SKILL.md § Run step 2)", file=sys.stderr)
        return 1
    try:
        meaning = json.loads(meaning_path.read_text(encoding="utf-8")) if meaning_path.exists() else {}
    except json.JSONDecodeError as e:
        print(f"meaning.json is not valid JSON: {e}", file=sys.stderr)
        return 1
    if shape := meaning_errors(meaning, structure):
        print("\n".join(shape), file=sys.stderr)
        return 1
    prev_path = out / "code-map.json"
    previous = None if a.relayout or not prev_path.exists() else json.loads(prev_path.read_text(encoding="utf-8"))
    cmap = assemble(structure, meaning, previous)
    errors = mapcheck.check(cmap)
    ensure_repo_files(a.repo, out_dir)
    if errors:
        (out / "code-map.invalid.json").write_text(json.dumps(cmap, indent=1), encoding="utf-8")
        print("\n".join(errors), file=sys.stderr)
        return 1
    (out / "code-map.json").write_text(json.dumps(cmap, indent=1), encoding="utf-8")
    (out / "code-map.invalid.json").unlink(missing_ok=True)
    print(json.dumps(mapcheck.stats(cmap)))
    try:
        print(f"viewer: {view.write_page(out)}")
    except (OSError, ValueError) as e:   # the map is fine: never send the agent back to meaning.json for this
        print(f"code-map.json is valid; index.html not written: {e}", file=sys.stderr)
        return 3
    (out / "meaning.previous.json").unlink(missing_ok=True)   # the full rescan it seeded is done
    print(audit.audit_out(out, out_dir, full=a.full_audit))   # never blocks: the map is written
    return 0


if __name__ == "__main__":
    sys.exit(main())
