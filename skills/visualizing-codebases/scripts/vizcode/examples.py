"""Examples (SKILL.md § Examples, format.md § Examples): which entry points and data types a map should have
examples for, the checks assemble.py makes on them, the fingerprints it stamps, and the staleness diff.py flags."""
from __future__ import annotations

from .calls import _abstractions
from .fingerprint import entry_fingerprint, type_fingerprint

LABEL = "example values, not computed"
ENTRY_KINDS = ("request", "event", "stream", "batch")          # a relation of these kinds ending at a method
TRACE_KINDS = ("calls", "request", "event", "stream", "batch", "db-read", "db-write", "ext-call", "hand-off")
HOPS = 2
CONTAINER_KINDS = ("service", "library", "package", "file", "class")
STALE_HINT = "stale — rewrite its value against the code, or delete it when its {gone} is gone; then delete the flag"


def empty() -> dict:
    return {"types": {}, "entries": []}


def entry_points(cmap: dict) -> dict[str, list[str]]:
    """Every entry point -> its keys, both sorted: the handler of a route fact in `files` (`METHOD path`) and the
    method a request, event, stream or batch relation ends at (the relation's key). One key per route: a route
    fact whose path a relation key of the same method ends at the end of (`POST /orders` and `POST /v1/orders`, the
    mount prefix added) is that key. Handlers that are not methods (a file, a service) are not entry points."""
    kinds = {n["id"]: n.get("kind") for n in cmap.get("nodes", [])}
    keys: dict[str, set[str]] = {}
    for r in cmap.get("relations", []):
        if r.get("kind") in ENTRY_KINDS and kinds.get(r.get("to")) == "method":
            keys.setdefault(r["to"], set()).update([r["key"]] if r.get("key") else [])
    for info in (cmap.get("files") or {}).values():
        for r in info.get("routes", []):
            if kinds.get(r.get("handler")) == "method":
                have = keys.setdefault(r["handler"], set())
                if not any(_mounted(k, r["method"], r["path"]) for k in have):
                    have.add(f"{r['method']} {r['path']}")
    return {m: sorted(k) for m, k in sorted(keys.items())}


def _mounted(key: str, method: str, path: str) -> bool:
    """Is the relation key `key` the route `method path`, with or without a mount prefix?"""
    verb, _, full = key.partition(" ")
    return verb == method and (full == path or (path != "/" and full.endswith(path) and full[: -len(path)]
                                                .startswith("/")))


def _refs(method: dict) -> list[str]:
    """The class ids a method's signature refers to, parameters first, each once."""
    sig = method.get("signature") or {}
    ids = [c for p in sig.get("params", []) for c in p.get("refs", [])] + list(sig.get("returns_refs", []))
    return list(dict.fromkeys(ids))


def _implementations(cmap: dict) -> dict[str, list[str]]:
    """Method id -> the methods that implement it: the inverse of calls.py `_abstractions`, the rule the scanner
    folds calls with (same name, same arity, else any arity when no same-arity method exists), so folding and
    unfolding cannot drift. The map's calls point at the trait method."""
    out: dict[str, list[str]] = {}
    for impl, top in _abstractions({n["id"]: n for n in cmap.get("nodes", [])}).items():
        out.setdefault(top, []).append(impl)
    return {k: sorted(v) for k, v in out.items()}


def seeds(cmap: dict, start: str) -> list[str]:
    """Where a trace from `start` begins, as the viewer seeds it (viewer src/trace/entries.ts `seedsFor`): a datastore
    at its tables (itself with none); a service, library, package, file or class at the entry points inside it, else at
    its boundary methods (methods inside it at one end of a trace relation whose other end is outside it), else at
    itself; anything else at itself. Every seed (the viewer folds above 5 for display only), sorted."""
    nodes = {n["id"]: n for n in cmap.get("nodes", [])}
    kind = nodes.get(start, {}).get("kind")
    if kind == "datastore":
        return sorted(n["id"] for n in cmap.get("nodes", []) if n.get("kind") == "table" and n.get("parent") == start) or [start]
    if kind not in CONTAINER_KINDS:
        return [start]

    def inside(nid: str) -> bool:
        seen, p = set(), nodes.get(nid, {}).get("parent")
        while p and p not in seen:
            if p == start:
                return True
            seen.add(p)
            p = nodes.get(p, {}).get("parent")
        return False

    entries = sorted(m for m in entry_points(cmap) if inside(m))
    if entries:
        return entries
    edge = set()
    for r in cmap.get("relations", []):
        if r.get("kind") not in TRACE_KINDS:
            continue
        for end, other in ((r["from"], r["to"]), (r["to"], r["from"])):
            if nodes.get(end, {}).get("kind") == "method" and inside(end) and not (other == start or inside(other)):
                edge.add(end)
    return sorted(edge) or [start]


def downstream(cmap: dict, start: str, hops: int = HOPS) -> list[str]:
    """Node ids within `hops` steps downstream of `start`: start first, then by distance, ids sorted within one
    distance. Edges are the trace relations as stored, except db-read, which runs table -> reader.
    The walk starts from `seeds(start)`: a datastore's tables, a container's entry points or boundary
    methods. A trait's method also reaches the same-named methods of its implementers, at its own
    distance (no hop)."""
    nxt: dict[str, set[str]] = {}
    for r in cmap.get("relations", []):
        if r.get("kind") in TRACE_KINDS:
            a, b = (r["to"], r["from"]) if r["kind"] == "db-read" else (r["from"], r["to"])
            nxt.setdefault(a, set()).add(b)
    impls = _implementations(cmap)
    seen: set[str] = set()

    def level(ids) -> list[str]:
        """`ids` plus the implementations of any trait method among them, none seen before; sorted."""
        grown, todo = set(), list(ids)
        while todo:
            x = todo.pop()
            if x in seen or x in grown:
                continue
            grown.add(x)
            todo.extend(impls.get(x, ()))
        return sorted(grown)

    first = seeds(cmap, start)               # as the viewer's reach seeds it (spec any-box A7)
    frontier = first + [x for x in level(first) if x not in first]
    seen.update(frontier)
    order = list(frontier)
    for _ in range(hops):
        frontier = level({b for a in frontier for b in nxt.get(a, ()) if b not in seen})
        seen.update(frontier)
        order += frontier
    return order


def wanted(cmap: dict, pins: list[dict] | None = None) -> dict:
    """What a map should have examples for: {"entries": {method id: [keys]}, "types": {class id: [why, ...]}}.
    Types are classes with fields in the refs of an entry point's handler, or of a method within HOPS steps
    downstream of a pin's start (`pins`; default the map's own). Not every type in the codebase."""
    nodes = {n["id"]: n for n in cmap.get("nodes", [])}
    entries = entry_points(cmap)
    types: dict[str, list[str]] = {}

    def add(method_id: str, why: str) -> None:
        m = nodes.get(method_id)
        if not m or m.get("kind") != "method":
            return
        for cid in _refs(m):
            c = nodes.get(cid)
            if c and c.get("kind") == "class" and c.get("fields"):
                reasons = types.setdefault(cid, [])
                if why not in reasons:
                    reasons.append(why)

    for m in entries:
        add(m, f"entry point {m}")
    for p in cmap.get("pins", []) if pins is None else pins:
        if p.get("start") in nodes:
            for nid in downstream(cmap, p["start"]):
                add(nid, f"within {HOPS} hops of pin {p.get('id')}")
    return {"entries": entries, "types": dict(sorted(types.items()))}


def shape_errors(examples: dict) -> list[str]:
    """Meaning.json's `examples` shape, before assembling: {types: {class id: {value: {...}}},
    entries: [{node, key, request, response?}]}."""
    out: list[str] = []
    types, entries = examples.get("types", {}), examples.get("entries", [])
    if not isinstance(types, dict):
        out.append("examples.types must be an object keyed by class id")
        types = {}
    if not isinstance(entries, list):
        out.append("examples.entries must be a list")
        entries = []
    for cid, e in types.items():
        if not isinstance(e, dict) or not isinstance(e.get("value"), dict):
            out.append(f"example type {cid}: needs a value object whose keys are the class's field names")
    for i, e in enumerate(entries, 1):
        if (not isinstance(e, dict) or "request" not in e
                or not all(isinstance(e.get(k), str) and e[k] for k in ("node", "key"))):
            out.append(f"example entry {i}: needs node (the handler method id), key and request")
    return out


def field_names(cid: str, nodes: dict[str, dict]) -> list[str]:
    """The fields an example of class `cid` may fill: its own, then those of the repo classes it extends."""
    out, todo, seen = [], [cid], set()
    while todo:
        c = todo.pop(0)
        if c in seen or c not in nodes:
            continue
        seen.add(c)
        out += [f["name"] for f in nodes[c].get("fields") or [] if f["name"] not in out]
        todo += nodes[c].get("implements") or []
    return out


def check(cmap: dict) -> list[str]:
    """Assemble.py's refusals for an assembled map's examples, as a fix list (format.md § Examples)."""
    nodes = {n["id"]: n for n in cmap.get("nodes", [])}
    ex = cmap.get("examples") or empty()
    errors: list[str] = []
    for cid, e in ex.get("types", {}).items():
        n = nodes.get(cid)
        if n is None or n.get("kind") != "class" or not n.get("fields"):
            errors.append(f"example type {cid}: not a class with fields — key it by the id of a class that declares "
                          "fields (find.py OUT/code-map.json NAME --kind class), or delete it")
        else:
            names = field_names(cid, nodes)
            if extra := [k for k in e.get("value", {}) if k not in names]:
                errors.append(f"example type {cid}: {', '.join(extra)} not among its fields ({', '.join(names)}) — "
                              "rename or drop them; a field left out is fine")
        if e.get("stale"):
            errors.append(f"example type {cid}: " + STALE_HINT.format(gone="class"))
    seen: set[tuple] = set()
    for i, e in enumerate(ex.get("entries", []), 1):
        where = f"example entry {i} ({e.get('node')} · {e.get('key')})"
        if nodes.get(e.get("node"), {}).get("kind") != "method":
            errors.append(f"{where}: node is not a method — use the handler method's id")
        if e.get("stale"):
            errors.append(f"{where}: " + STALE_HINT.format(gone="handler"))
        if (e.get("node"), e.get("key")) in seen:
            errors.append(f"{where}: duplicates an earlier entry example with the same node and key — merge them")
        seen.add((e.get("node"), e.get("key")))
    return errors


def _class_with_fields(n: dict | None) -> bool:
    return n is not None and n.get("kind") == "class" and bool(n.get("fields"))


def _method(n: dict | None) -> bool:
    return n is not None and n.get("kind") == "method"


def stamped(examples: dict | None, nodes: dict[str, dict]) -> dict:
    """A copy of `examples` with a fresh `fingerprint` on each example whose class or handler is in `nodes` (one the
    agent wrote is overwritten); an example whose class or handler is missing gets none (check() refuses it)."""
    ex = examples or empty()
    types = {}
    for cid, e in ex.get("types", {}).items():
        e = {k: v for k, v in e.items() if k != "fingerprint"}
        if _class_with_fields(nodes.get(cid)):
            e["fingerprint"] = type_fingerprint(nodes[cid])
        types[cid] = e
    entries = []
    for e in ex.get("entries", []):
        e = {k: v for k, v in e.items() if k != "fingerprint"}
        if _method(nodes.get(e.get("node"))):
            e["fingerprint"] = entry_fingerprint(nodes[e["node"]], nodes)
        entries.append(e)
    return {"types": types, "entries": entries}


def _field_diff(cls: dict | None, value, nodes: dict[str, dict] | None = None) -> dict:
    """What a stale type example's value misses against its class now: `value_lacks` (fields the value has no key
    for, such as a field added since) and `value_extra` (keys that are no longer fields); empty lists left out."""
    if not _class_with_fields(cls) or not isinstance(value, dict):
        return {}
    names = field_names(cls["id"], nodes) if nodes else [f["name"] for f in cls["fields"]]
    diff = {"value_lacks": [f for f in names if f not in value], "value_extra": [k for k in value if k not in names]}
    return {k: v for k, v in diff.items() if v}


def flag_stale(examples: dict | None, nodes: dict[str, dict]) -> tuple[dict, list[dict]]:
    """The previous map's examples against a new structure's `nodes`: each whose class or handler is gone (or the class
    lost its fields), or whose stored fingerprint differs from the one recomputed now, gets `stale: true`. Returns
    (examples, what was flagged: `{"type": class id}` or `{"entry": node, "key": key}`, each with `why`, types
    first)."""
    ex = examples or empty()
    flagged: list[dict] = []
    types = {}
    for cid, e in ex.get("types", {}).items():
        n = nodes.get(cid)
        why = ("the class is gone" if n is None else "the class has no fields" if not _class_with_fields(n)
               else "its fields changed" if type_fingerprint(n) != e.get("fingerprint")
               else "still flagged" if e.get("stale") else None)
        types[cid] = {**e, "stale": True} if why else e
        if why:
            flagged.append({"type": cid, **_field_diff(n, e.get("value"), nodes), "why": why})
    entries = []
    for e in ex.get("entries", []):
        n = nodes.get(e.get("node"))
        why = ("the handler is gone" if not _method(n)
               else "its handler's signature, or a type it takes or returns, changed"
               if entry_fingerprint(n, nodes) != e.get("fingerprint") else "still flagged" if e.get("stale") else None)
        entries.append({**e, "stale": True} if why else e)
        if why:
            flagged.append({"entry": e.get("node"), "key": e.get("key"), "why": why})
    return {"types": types, "entries": entries}, flagged
