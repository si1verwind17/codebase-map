#!/usr/bin/env python3
"""Print config files with every value that may be a credential hidden (SKILL.md § Never read secrets).

Usage: config.py FILE [FILE ...]
       config.py --repo REPO --commit COMMIT PATH [PATH ...]   (the files at a commit, as `git show` reads them)
Prints `== FILE`, then `line: text` for each line, credentials as <hidden>. A real env file (`.env`, `.env.*`,
`*.env`; not a template) is refused: list its key names only.
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

from vizcode.scan import secrets  # noqa: E402

ENV_FILES = (".env", ".env.*", "*.env")
TEMPLATES = ("*.example", "*.sample", "*.template", "*.example.*", "*.sample.*", "*.template.*")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--repo", type=Path)
    ap.add_argument("--commit")
    a = ap.parse_args(argv)
    if (a.repo is None) != (a.commit is None):
        ap.error("--repo and --commit go together")
    status = 0
    for f in a.files:
        name = f.name
        if any(fnmatch.fnmatch(name, p) for p in ENV_FILES) and not any(fnmatch.fnmatch(name, p) for p in TEMPLATES):
            print(f"{f}: a real env file: key names only (SKILL.md § Never read secrets)", file=sys.stderr)
            status = 1
            continue
        if a.repo is not None:
            got = subprocess.run(["git", "-C", str(a.repo), "show", f"{a.commit}:./{f.as_posix()}"],
                                 capture_output=True)
            if got.returncode:
                print(f"{f}: not in {a.commit}", file=sys.stderr)
                status = 1
                continue
            text = got.stdout.decode("utf-8", errors="replace")
        else:
            text = f.read_text(encoding="utf-8", errors="replace")
        print(f"== {f}")
        for no, line in secrets.mask(text):
            print(f"{no}: {line}")
    return status


if __name__ == "__main__":
    sys.exit(main())
