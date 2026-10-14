#!/usr/bin/env python3
"""Look up node ids in structure.json (or code-map.json) without reading the whole file.

Usage: find.py MAP_JSON TEXT [--kind method|class|file|package] [--limit 30]
Prints one line per match: id  file:line  (params) -> returns
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
    hits = [n for n in nodes if a.text.lower() in n["id"].lower() and (a.kind is None or n["kind"] == a.kind)]
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
