"""Which way data moves on a runtime relation: forward (from → to), back (to → from) or both."""
from __future__ import annotations

DATA_DEFAULTS = {"request": "forward", "event": "forward", "batch": "forward", "db-write": "forward",
                 "ext-call": "forward", "db-read": "back", "hand-off": "forward"}  # stream: no default, the meaning pass decides
DATA_VALUES = ("forward", "back", "both")


def apply_defaults(relations: list[dict]) -> None:
    for r in relations:
        if r["kind"] in DATA_DEFAULTS:
            r.setdefault("data", DATA_DEFAULTS[r["kind"]])


def oriented(r: dict) -> tuple[str, str]:
    """(upstream, downstream) by data direction; `both` keeps the caller first."""
    return (r["to"], r["from"]) if r.get("data") == "back" else (r["from"], r["to"])
