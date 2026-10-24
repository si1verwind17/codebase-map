#!/usr/bin/env python3
"""List the examples a map should have (SKILL.md § Examples): every entry point (above 100, those on a pin's trace; the
rest marked optional), and every data type in the refs of such an entry point's handler or of a method within two
hops downstream of a pin's start, each marked ok, missing or stale. Examples are for data types (payloads, records,
entities): skip any listed class that only holds services or dependencies (marked when its fields' types say so).

Usage: examples.py REPO [--out-dir docs/viz-code]
Reads OUT/code-map.json (run assemble.py first) and, when it exists, OUT/meaning.json, whose pins and examples are
newer than the map's. Totals first, nothing left out. Exit 0; 2 when there is no map to read.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vizcode import examples, gitsrc  # noqa: E402


def _mark(found: list[dict]) -> str:
    return "missing" if not found else "stale" if any(x.get("stale") for x in found) else "ok"


def _entry_mark(keys: list[str], found: list[dict]) -> str:
    """The mark of an entry point: `missing` with how many of its several keys have an example when only some do
    (`missing 1/3 keys`, after `stale, ` when one is stale), and each example key that is no longer one of its keys
    (`ok, key gone: POST /old`)."""
    mark = _mark(found)
    have = {e.get("key") for e in found}
    if mark != "missing" and len(keys) > 1 and (n := sum(k in have for k in keys)) < len(keys):
        mark = f"{mark + ', ' if mark != 'ok' else ''}missing {n}/{len(keys)} keys"
    if gone := sorted(k for k in have if k not in keys):
        mark += f", key gone: {'; '.join(map(str, gone))}"
    return mark


def report(cmap: dict, meaning: dict | None) -> str:
    """The checklist: entry points then data types, each section's total and missing count first."""
    source = meaning if meaning is not None else cmap
    have = source.get("examples") or examples.empty()
    pins = source.get("pins", [])
    want = examples.wanted(cmap, pins)
    _, total = examples.required(cmap, pins)
    nodes = {n["id"]: n for n in cmap.get("nodes", [])}
    by_node: dict[str, list[dict]] = {}
    for e in have.get("entries", []):
        by_node.setdefault(e.get("node"), []).append(e)
    entries = [(m, keys, _entry_mark(keys, by_node.get(m, []))) for m, keys in want["entries"].items()]
    rest = [(m, keys, "optional" if (mark := _entry_mark(keys, by_node.get(m, []))) == "missing" else mark)
            for m, keys in examples.entry_points(cmap).items() if m not in want["entries"]]
    types = [(c, why, _mark([have["types"][c]] if c in have.get("types", {}) else []))
             for c, why in want["types"].items()]
    some = sum("missing " in s for *_, s in entries)
    lines = [f"Entry points: {len(entries)} ({sum(s == 'missing' for *_, s in entries)} without an example"
             + (f", {some} missing some keys" if some else "") + ")"
             + (f"; the map has {total}, over {examples.ALL_ENTRIES}: only those on a pin's trace need one, the "
                f"other {len(rest)} are listed last as optional" if total else "")]
    lines += [f"- {s:<7}  {m}  {'; '.join(keys) or '(no key)'}" for m, keys, s in entries + rest]
    lines.append(f"Data types: {len(types)} ({sum(s == 'missing' for *_, s in types)} without an example)")
    lines += [f"- {s:<7}  {c}  fields: {', '.join(examples.field_names(c, nodes))}  — {'; '.join(why)}"
              + ("  (fields all collaborators: wiring, skip it)" if examples.wiring(c, nodes) else "")
              for c, why, s in types]
    return "\n".join(lines) + "\n"


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
    try:
        cmap = json.loads((out / "code-map.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(f"error: no readable {out / 'code-map.json'}; run assemble.py first", file=sys.stderr)
        return 2
    meaning = None
    if (out / "meaning.json").exists():
        try:
            meaning = json.loads((out / "meaning.json").read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"error: meaning.json is not valid JSON: {e}", file=sys.stderr)
            return 2
    sys.stdout.write(report(cmap, meaning))
    return 0


if __name__ == "__main__":
    sys.exit(main())
