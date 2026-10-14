#!/usr/bin/env python3
"""Validate an existing code-map.json. Usage: validate.py PATH/code-map.json"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vizcode import mapcheck  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    cmap = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    errors = mapcheck.check(cmap)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(json.dumps(mapcheck.stats(cmap)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
