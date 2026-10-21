#!/usr/bin/env python3
"""Structure pass over the committed HEAD of a repo.

Usage: extract.py REPO [--out-dir docs/viz-code] [--exclude GLOB ...]
Writes <REPO>/<out-dir>/structure.json and summary.md. Each --exclude glob is added to <out-dir>/stack.yaml's
`exclude` list, which every later run applies.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vizcode import gitsrc, stack, structure  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out-dir", default="docs/viz-code")
    ap.add_argument("--exclude", action="append", default=[])
    a = ap.parse_args(argv)
    try:
        out_dir = gitsrc.rel_out_dir(a.repo, a.out_dir)
        stack_file = a.repo / out_dir / "stack.yaml"
        if a.exclude:   # kept in stack.yaml: a rescan without the flag leaves the same files out
            stack.add_excludes(stack_file, a.exclude)
        if stack_file.is_file():
            stack.ensure_header(stack_file)
        s = structure.build(a.repo, out_dir, a.exclude)
    except (gitsrc.GitError, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = a.repo / out_dir
    out.mkdir(parents=True, exist_ok=True)
    (out / "structure.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    (out / "summary.md").write_text(structure.summary_md(s), encoding="utf-8")
    print(json.dumps({"commit": s["meta"]["commit"], **s["stats"], "stack": stack.count(s["stack"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
