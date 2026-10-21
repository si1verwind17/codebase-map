"""`ctor` on class nodes: the method that builds the class, `{method}` plus `of` when several could; Scala class
parameters and a Kotlin or C# primary constructor are the class's own `{params, line}`, set by the adapters."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

NAMED = {"python": "__init__", "ruby": "initialize", "php": "__construct", "typescript": "constructor",
         "tsx": "constructor", "javascript": "constructor", "rust": "new"}
OWN_NAME = ("java", "csharp")          # a constructor is named as its class


def _folder(n: dict) -> str:
    return PurePosixPath(n["file"]).parent.as_posix()


def _returned(returns: str) -> set[str]:
    """The unqualified type names in a Go return text (`*Store`, `(*Store, error)`, `(s *Store, err error)`): a type of
    the package itself is never qualified, so another package's (`http.Handler`) is left out, as is an element type
    of a slice, array, map or channel (`[]*Store`, `map[string]*Store` build no Store)."""
    out: set[str] = set()
    for part in returns.strip("()").split(","):
        words = part.split()
        if len(words) == 2 and words[0].isidentifier() and words[0] != "chan":
            words = words[1:]                      # a named result
        if m := re.fullmatch(r"(?!map\[)(\w+)(\[.*)?", " ".join(words).lstrip("*&")):
            out.add(m.group(1))
    return out


def mark(nodes: list[dict], values: set[str] = frozenset(), class_inits: set[str] = frozenset()) -> None:
    """Set `ctor: {method}` on each class node a method builds, with `of` when several could: the one with the
    most parameters, the first by file and line on a tie. A class whose own parameters an adapter set as its `ctor`
    (`{params, line}`) counts them as one more candidate, kept when it wins (`of` added when there are several). A
    class that already has a `{method}` `ctor`, a value whose own parameters are its fields (`values`: Java and C#
    records, Java enums, Kotlin data classes) and a Go interface (a class some class `implements`) are left as they
    are; a class's own initializer (`class_inits`: a C# static constructor) builds nothing."""
    files = {n["id"] for n in nodes if n["kind"] == "file"}
    by_parent: dict[str, list[dict]] = {}
    factories: dict[str, list[dict]] = {}          # Go `New...` functions, per folder
    for n in nodes:
        if n["kind"] != "method":
            continue
        by_parent.setdefault(n["parent"], []).append(n)
        if n.get("lang") == "go" and n["parent"] in files and n["name"].startswith("New"):
            factories.setdefault(_folder(n), []).append(n)
    interfaces = {i for n in nodes for i in n.get("implements", ())}
    for c in nodes:
        own = c.get("ctor") if c["kind"] == "class" and "params" in c.get("ctor", {}) else None
        if c["kind"] != "class" or ("ctor" in c and own is None) or c["id"] in values:
            continue
        lang = c.get("lang")
        if lang == "go":
            if c["id"] in interfaces:
                continue
            cands = [m for m in factories.get(_folder(c), [])
                     if c["name"] in _returned((m.get("signature") or {}).get("returns") or "")]
        else:
            name = c["name"] if lang in OWN_NAME else NAMED.get(lang)
            cands = [m for m in by_parent.get(c["id"], []) if m["name"] == name and m["id"] not in class_inits]
        if not cands:
            continue
        # (sort key, method id): on a tie the primary constructor, written before the body, comes first
        rank = [((-len((m.get("signature") or {}).get("params", [])), m["file"], m["line"], 1, m["id"]), m["id"])
                for m in cands]
        if own is not None:   # a primary constructor besides explicit ones (C#)
            rank.append(((-len(own["params"]), c["file"], own["line"], 0, ""), None))
        best, of = min(rank, key=lambda x: x[0])[1], {"of": len(rank)} if len(rank) > 1 else {}
        c["ctor"] = {**own, **of} if best is None else {"method": best, **of}
