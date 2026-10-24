#!/usr/bin/env python3
"""Look up node ids in structure.json (or code-map.json) without reading the whole file.

Usage: find.py MAP_JSON TEXT [--kind method|class|file|package] [--limit 30]
Prints one line per match (the node named TEXT first, then ids ending in it, then any id holding it):
id  file:line  (params) -> returns
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("map_json", type=Path)
    ap.add_argument("text")
    ap.add_argument("--kind")
    ap.add_argument("--limit", type=int, default=30)
    a = ap.parse_args(argv)
    nodes = json.loads(a.map_json.read_text(encoding="utf-8"))["nodes"]
    want = a.text.lower()
    hits = [n for n in nodes if want in n["id"].lower() and (a.kind is None or n["kind"] == a.kind)]
    # the node named TEXT first, then ids ending in it, then the rest: on a large map the one meant is not cut
    hits.sort(key=lambda n: (str(n.get("name", "")).lower() != want, not n["id"].lower().endswith(want)))
    for n in hits[:a.limit]:
        sig = n.get("signature")
        sig_text = ""
        if sig:
            params = ", ".join(f"{p['name']}: {p['type']}" if p["type"] else p["name"] for p in sig["params"])
            sig_text = f"  ({params}) -> {sig['returns']}"
        print(f"{n['id']}  {n.get('file', '')}:{n.get('line', '')}{sig_text}")
    if len(hits) > a.limit:
        print(f"... {len(hits) - a.limit} more")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())
