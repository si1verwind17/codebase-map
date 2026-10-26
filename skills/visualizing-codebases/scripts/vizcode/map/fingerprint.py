"""Fingerprints of data types and entry points (spec: traces §1.4), computed from the map's nodes, never stored on
them. `assemble.py` stamps them on examples and `diff.py` recomputes them against a new structure: an example
whose stored fingerprint differs is stale."""
from __future__ import annotations

import hashlib
import json

LENGTH = 12     # hex characters kept of the sha256


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()[:LENGTH]


def type_fingerprint(node: dict) -> str:
    """A class's fields in declared order, name and type text: same fields, same digest. A node without
    `fields` digests as no fields."""
    return _digest([[f["name"], f.get("type")] for f in node.get("fields") or []])


def entry_fingerprint(method: dict, nodes_by_id: dict[str, dict]) -> str:
    """A handler method's signature (parameter names and types, return type) plus the type fingerprint of every
    class in its `refs` and `returns_refs`, one level deep. A ref missing from `nodes_by_id` counts as `null`."""
    sig = method.get("signature") or {"params": [], "returns": None}
    refs = sorted({r for p in sig["params"] for r in p.get("refs") or []} | set(sig.get("returns_refs") or []))
    return _digest({"params": [[p["name"], p.get("type")] for p in sig["params"]],
                    "returns": sig.get("returns"),
                    "types": {r: type_fingerprint(nodes_by_id[r]) if r in nodes_by_id else None for r in refs}})
