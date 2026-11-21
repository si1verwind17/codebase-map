"""code-map.json as it is written: no indentation, one record per line (a node, a relation, a floor, a file's facts,
an example), so the file is about a sixth smaller than indented JSON and a line search still finds one record per hit."""
from __future__ import annotations

import json

DEEP = {"layout": 2, "examples": 2}   # top-level keys whose values hold a second level of records (floors, types)


def _compact(v) -> str:
    return json.dumps(v, separators=(",", ":"), ensure_ascii=False)


def _block(v, indent: str, levels: int) -> str:
    """`v` with each element on its own line, `levels` levels deep; anything shallower or scalar on one line."""
    if levels <= 0 or not isinstance(v, (list, dict)) or not v:
        return _compact(v)
    inner = indent + " "
    if isinstance(v, list):
        rows = [inner + _block(x, inner, levels - 1) for x in v]
        return "[\n" + ",\n".join(rows) + "\n" + indent + "]"
    rows = [f"{inner}{_compact(k)}:{_block(x, inner, levels - 1)}" for k, x in v.items()]
    return "{\n" + ",\n".join(rows) + "\n" + indent + "}"


def dumps(cmap: dict) -> str:
    """The map's text: each top-level key on a line, the records of its list or object one per line below it."""
    rows = [f" {_compact(k)}:{_block(v, ' ', DEEP.get(k, 1) if k != 'meta' else 0)}" for k, v in cmap.items()]
    return "{\n" + ",\n".join(rows) + "\n}\n"
