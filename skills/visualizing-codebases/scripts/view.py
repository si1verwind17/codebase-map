#!/usr/bin/env python3
"""Write OUT/index.html: the prebuilt viewer with this map built in. (The field guide is on the project's site.)

Usage: view.py REPO [--out-dir docs/viz-code]
Maps over 8 MB are not built in: the page asks for code-map.json instead.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vizcode import gitsrc, readme  # noqa: E402

VIEWER = Path(__file__).resolve().parent.parent / "viewer" / "dist" / "viewer.html"
MARKER = "/*CODE_MAP*/"
INLINE_LIMIT = 8 * 1024 * 1024


def render(map_text: str, viewer_html: str) -> tuple[str, bool]:
    """(page, inlined). The map goes inside a <script type="application/json">: every `<` becomes `\\u003c`
    (only possible inside JSON strings, so it stays valid JSON) and no `</script>` or `<!--` can reach the parser."""
    if MARKER not in viewer_html:
        raise ValueError("viewer.html has no map marker; rebuild the viewer")
    if len(map_text.encode()) > INLINE_LIMIT:
        return viewer_html, False
    return viewer_html.replace(MARKER, map_text.replace("<", "\\u003c"), 1), True


def with_header(page: str, file: str) -> str:
    """The generated-file comment as the first line inside <head> (a page without a <head> is left as it is)."""
    return page.replace("<head>", "<head>\n" + readme.header(file), 1)


def write_page(out: Path) -> str:
    """Write OUT/index.html from OUT/code-map.json; returns the line to report."""
    page, inlined = render((out / "code-map.json").read_text(encoding="utf-8"), VIEWER.read_text(encoding="utf-8"))
    (out / "index.html").write_text(with_header(page, "index.html"), encoding="utf-8")
    return f"{out / 'index.html'}" + ("" if inlined else "  (map over 8 MB: open it from the page)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out-dir", default="docs/viz-code")
    a = ap.parse_args(argv)
    try:
        out = a.repo / gitsrc.rel_out_dir(a.repo, a.out_dir)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    cmap = out / "code-map.json"
    if not cmap.exists():
        print(f"error: {cmap} not found; run assemble.py first", file=sys.stderr)
        return 2
    print(write_page(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
