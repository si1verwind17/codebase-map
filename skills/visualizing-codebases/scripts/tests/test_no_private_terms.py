"""The skill is public: no file under it names a private project. The terms (one per line) live only on the
maintainer's machine, in ~/.config/viz-code/private-terms.txt (VIZCODE_PRIVATE_TERMS overrides the path); the test
skips without that file."""
import os
import subprocess
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[2]
TERMS = Path(os.environ.get("VIZCODE_PRIVATE_TERMS", Path.home() / ".config/viz-code/private-terms.txt"))
SKIP_DIRS = {"node_modules", ".pytest_cache", "__pycache__", ".vite", ".svelte-kit", ".git"}   # dist ships: scanned


def _terms() -> list[str]:
    lines = TERMS.read_text(encoding="utf-8").splitlines()
    return [t.strip().lower() for t in lines if t.strip() and not t.strip().startswith("#")]


def _walk():
    for root, dirs, files in os.walk(SKILL):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            yield Path(root, f)


def _files():
    """Git-tracked files under the skill (what ships); falls back to walking the disk without git."""
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--", "."], cwd=SKILL, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        yield from _walk()
        return
    for name in sorted(n for n in out.decode("utf-8", errors="surrogateescape").split("\0") if n):
        p = SKILL / name
        if p.is_file():
            yield p


@pytest.mark.skipif(not TERMS.is_file(), reason="no private terms file on this machine")
def test_no_private_terms_under_the_skill():
    terms = _terms()
    hits = []
    for p in _files():
        text = p.read_bytes().decode("utf-8", errors="ignore")
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            hits += [f"{p.relative_to(SKILL)}:{n}: {t}" for t in terms if t in low]
    assert hits == [], "private terms under the skill:\n" + "\n".join(hits)
