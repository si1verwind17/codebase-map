"""Stable node and relation ids: qualified names, never line numbers."""
from __future__ import annotations


def mod_path(module_id: str) -> str:
    return module_id.removeprefix("mod:")


def package_id(module_id: str, package: str) -> str:
    return f"{mod_path(module_id)}::{package}/"


def qualified(module_id: str, qname: str) -> str:
    return f"{mod_path(module_id)}::{qname}"


def method_id(owner_id: str, name: str, arity: int) -> str:
    return f"{owner_id}#{name}/{arity}"


def relation_id(kind: str, frm: str, to: str, key: str | None) -> str:
    return f"r:{kind}:{frm}->{to}:{key or ''}"


class IdRegistry:
    """Makes ids unique in source order: a second `f/1` becomes `f/1~2`."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def claim(self, nid: str) -> str:
        n = self._seen.get(nid, 0) + 1
        self._seen[nid] = n
        return nid if n == 1 else f"{nid}~{n}"
