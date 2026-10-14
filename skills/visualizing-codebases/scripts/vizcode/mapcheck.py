"""Checks a code-map: schema, then the rules a schema cannot express."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import jsonschema

from . import examples, pins
from .assemble import default_store

SCHEMA = json.loads((Path(__file__).resolve().parent.parent / "schema" / "code-map.schema.json").read_text(encoding="utf-8"))
RUNTIME_KINDS = {"request", "event", "stream", "batch", "db-read", "db-write", "ext-call"}
STALE_HINT = "stale — re-resolve it: keep it (delete the flag), change it, or drop it"
PARENT_KINDS = {
    "service": {None}, "library": {None}, "datastore": {None}, "external": {None}, "topic": {None},
    "package": {"service", "library"}, "class": {"package", "class", "file"}, "file": {"package"},
    "method": {"class", "file"}, "table": {"datastore"},
}
NODE_FIELD_KIND = {"delivery": "topic", "dead_letter_of": "topic", "replicas": "service", "store": "datastore"}
RELATION_FIELD_KIND = {"subscription": "event", "group": "event", "on_failure": "event",
                       "schedule": "batch", "job": "batch"}


CRON_FIELD = re.compile(r"[0-9*?/,\-LW#]+|[A-Za-z]{3}([-,][A-Za-z]{3})*")


def _bad_schedule_entry(entry: str) -> bool:
    if entry == "manual" or re.fullmatch(r"on .*\S.*", entry):
        return False
    fields = entry.split()
    return not (len(fields) in (5, 6) and all(CRON_FIELD.fullmatch(f) for f in fields))


def check(cmap: dict) -> list[str]:
    errors = [f"schema: {'/'.join(map(str, e.absolute_path))}: {e.message}"
              for e in jsonschema.Draft202012Validator(SCHEMA).iter_errors(cmap)]
    if errors:
        return errors
    nodes = {}
    for n in cmap["nodes"]:
        if n["id"] in nodes:
            errors.append(f"duplicate node id {n['id']}")
        nodes[n["id"]] = n
    for n in cmap["nodes"]:
        parent = n.get("parent")
        pkind = nodes[parent]["kind"] if parent in nodes else None
        if parent is not None and parent not in nodes:
            errors.append(f"node {n['id']}: parent {parent} missing")
        elif pkind not in PARENT_KINDS[n["kind"]]:
            errors.append(f"node {n['id']}: {n['kind']} cannot sit under {pkind or 'nothing'}")
        if n["kind"] == "service" and not n.get("evidence"):   # a deployable is always declared somewhere
            errors.append(f"node {n['id']}: service needs evidence (the line that deploys it: compose, "
                          "Dockerfile, build, orchestrator registration, or the documented run command)")
    for n in cmap["nodes"]:
        if n.get("stale"):
            errors.append(f"node {n['id']}: {STALE_HINT}")
        needs = [f for f in ("delivery", "dead_letter_of") if f in n and n["kind"] == "topic"]
        if n["kind"] == "service" and "replicas" in n:
            needs.append("replicas")
        if n["kind"] == "datastore" and n.get("store", default_store(n["id"])) != default_store(n["id"]):
            needs.append("store")
        if needs and not n.get("evidence"):
            errors.append(f"node {n['id']}: {', '.join(needs)} needs evidence (cite the line that shows it: "
                          "the broker or subscription config, the compose or k8s replicas line, or the client setup)")
        for field, kind in NODE_FIELD_KIND.items():
            if field in n and n["kind"] != kind:
                errors.append(f"node {n['id']}: {field} belongs on a {kind} node, not a {n['kind']} — delete it")
        dl = n.get("dead_letter_of")
        if dl is not None and n["kind"] == "topic":
            if dl == n["id"]:
                errors.append(f"node {n['id']}: dead_letter_of names the topic itself — name the topic whose failures land here")
            elif nodes.get(dl, {}).get("kind") != "topic":
                errors.append(f"node {n['id']}: dead_letter_of {dl} is not a topic — name the topic node "
                              "whose failed messages this one receives")

    def root(nid: str) -> dict:
        n, seen = nodes.get(nid, {}), set()
        while n.get("parent") in nodes and n["id"] not in seen:
            seen.add(n["id"])
            n = nodes[n["parent"]]
        return n

    rel_ids = set()
    for r in cmap["relations"]:
        if r.get("stale"):
            errors.append(f"relation {r['id']}: {STALE_HINT}")
        top = root(r["from"])
        if r["kind"] in RUNTIME_KINDS and top.get("kind") == "library":
            errors.append(f"relation {r['id']}: runtime relation starts inside library {top['id']} — "
                          "credit the service that runs it and name the library method in via")
        if r["id"] in rel_ids:
            errors.append(f"duplicate relation id {r['id']}")
        rel_ids.add(r["id"])
        for end in ("from", "to"):
            if r[end] not in nodes:
                errors.append(f"relation {r['id']}: {end} {r[end]} missing")
        if "via" in r and r["via"] not in nodes:
            errors.append(f"relation {r['id']}: via {r['via']} missing")
        if r["kind"] == "stream" and not r.get("data"):
            errors.append(f"relation {r['id']}: stream needs a data direction (forward, back or both)")
        if r.get("tables") and "*" not in (r.get("key") or ""):
            errors.append(f"relation {r['id']}: tables lists the concrete tables of a wildcard key "
                          "(`table schema.*`); this key names one table")
        if r["confidence"] == "inferred" and not r.get("why"):
            errors.append(f"relation {r['id']}: inferred without why")
        if r["kind"] == "event" and "topic" not in {nodes.get(r["from"], {}).get("kind"), nodes.get(r["to"], {}).get("kind")}:
            errors.append(f"relation {r['id']}: event must start or end at a topic node")
    for r in cmap["relations"]:
        for field, kind in RELATION_FIELD_KIND.items():
            if field in r and r["kind"] != kind:
                errors.append(f"relation {r['id']}: {field} belongs on {'an' if kind == 'event' else 'a'} "
                              f"{kind} relation, not a {r['kind']} — delete it")
        if r["kind"] == "event":
            if r.get("on_failure") and nodes.get(r["to"], {}).get("kind") != "topic":
                errors.append(f"relation {r['id']}: on_failure marks a publish to a topic (the dead-letter or "
                              "failure topic); this event does not end at one — delete it or point `to` at the topic")
            if nodes.get(r["from"], {}).get("kind") != "topic":
                for field in ("subscription", "group"):
                    if field in r:
                        errors.append(f"relation {r['id']}: {field} belongs on the consume side (an event that "
                                      "starts at a topic); this one publishes — move it to the consuming relation")
        for entry in r.get("schedule", []) if r["kind"] == "batch" else []:
            if _bad_schedule_entry(entry):
                errors.append(f'relation {r["id"]}: schedule entry "{entry}" is not a 5- or 6-field cron '
                              'expression, "manual" or "on <event>" — rewrite it in one of those forms')
    errors += examples.check(cmap)
    errors += pins.start_errors(cmap)
    errors += _check_layout(cmap, nodes)
    return errors


def _check_layout(cmap: dict, nodes: dict[str, dict]) -> list[str]:
    """The layout is the viewer's contract: every item is a node or group, no two items share a cell,
    and every child of a container is placed on its floor (directly, inside a group, or as a utility)."""
    errors = []
    containers = cmap["layout"]["containers"]
    groups = {g["id"]: g for c in containers.values() for g in c.get("groups", [])}
    for cid, c in containers.items():
        if cid != "site" and cid not in nodes and cid not in groups:
            errors.append(f"layout: container {cid} is not a node")
        cells = {}
        for iid, p in c["items"].items():
            if iid.startswith("twin:"):
                if iid[5:] not in (nodes.get(cid) or {}).get("twins", []):
                    errors.append(f"layout {cid}: item {iid} is not a twin of {cid}")
            elif iid not in nodes and iid not in groups:
                errors.append(f"layout {cid}: item {iid} is not a node")
            if p["region"] == "lane" and not any(l["id"] == iid for l in c.get("lanes", [])):
                errors.append(f"layout {cid}: {iid} sits on a lane the floor does not have")
            cell = (p["region"], p["col"], p["row"])
            if cell in cells:
                errors.append(f"layout {cid}: {iid} and {cells[cell]} share cell {cell} (overlap)")
            cells[cell] = iid

    def placed(cid: str) -> set[str]:
        out = set()
        for iid in containers.get(cid, {}).get("items", {}):
            out |= placed(iid) if iid in groups else {iid}
        return out

    children: dict[str, set[str]] = {}
    for n in nodes.values():
        if n.get("parent"):
            children.setdefault(n["parent"], set()).add(n["id"])
    top = {n["id"] for n in nodes.values() if n["kind"] in ("service", "library", "external", "topic", "datastore")}
    site_placed = placed("site") | set(containers.get("site", {}).get("utilities", []))
    for nid in sorted(top - site_placed):
        errors.append(f"layout site: {nid} is not placed")
    for cid, kids in children.items():
        if cid in containers and nodes[cid]["kind"] != "method":
            for nid in sorted(kids - placed(cid)):
                errors.append(f"layout {cid}: {nid} is not placed")
    for gid, g in groups.items():
        for m in g["members"]:
            for cid, c in containers.items():
                if gid in c["items"] and m in c["items"]:
                    errors.append(f"layout {cid}: {m} is both an item and a member of {gid}")
    return errors


def stats(cmap: dict) -> dict:
    return {"nodes": dict(Counter(n["kind"] for n in cmap["nodes"])),
            "relations": dict(Counter(r["kind"] for r in cmap["relations"])),
            "confidence": dict(Counter(r["confidence"] for r in cmap["relations"])),
            "pins": len(cmap.get("pins", [])),
            "examples": {"types": len(cmap.get("examples", {}).get("types", {})),
                         "entries": len(cmap.get("examples", {}).get("entries", []))},
            "problems": len(cmap["problems"])}


EXT_SUFFIXES = ("_URL", "_URI", "_HOST", "_ENDPOINT", "_TOKEN", "_API_KEY")
# words of a config key that say what kind of address it is, not whose: `ORDER_SERVICE_URL` names `order`
ROLE_WORDS = {"api", "service", "svc", "callback", "base", "endpoint", "server", "client", "ws", "wss", "http",
              "https", "grpc", "internal", "public", "rest", "webhook", "host", "url", "uri"}
WORD = re.compile(r"[a-z0-9]+")
ENV_LINE = re.compile(r"^- \*\*env keys:\*\* (.*)$", re.M)   # as structure.summary_md writes it


def _last_segment(name: str) -> str:
    return re.split(r"[./:#$]", name.rstrip("$/"))[-1]


def warnings(cmap: dict, summary_md: str | None = None) -> list[dict]:
    """Content warnings: things the map says that look wrong in the code's own terms, or are missing (an entry
    point without an example, a pin whose start is gone). Never block a build."""
    out: list[dict] = []
    nodes = {n["id"]: n for n in cmap.get("nodes", [])}
    if summary_md is not None:
        # a key is accounted for when the map names it: a node, a relation key, or a `problems` entry saying
        # why it is no endpoint (a test helper's, a tool's own setting)
        named = " ".join([f"{n['id']} {n.get('name', '')}" for n in nodes.values()]
                         + [r.get("key", "") or "" for r in cmap.get("relations", [])]
                         + [p.get("text", "") for p in cmap.get("problems", [])]).lower()
        owners = {n.get("name", "").lower() for n in nodes.values()
                  if n["kind"] in ("service", "external") and n.get("name")}
        owner_words = [set(WORD.findall(o)) - ROLE_WORDS for o in owners]
        seen: set[str] = set()
        for m in ENV_LINE.finditer(summary_md):
            for key in (k.strip() for k in m.group(1).split(";")):
                suffix = next((s for s in EXT_SUFFIXES if key.endswith(s)), None)
                if not suffix or key in seen:
                    continue
                seen.add(key)
                stem = key[:-len(suffix)].lower()
                words = [w for w in WORD.findall(stem) if w not in ROLE_WORDS]
                if stem and key.lower() not in named and stem.replace("_", "-") not in owners \
                        and stem not in owners and not (words and any(set(words) <= ow for ow in owner_words)):
                    out.append({"id": "ext.missing", "node": None,
                                "detail": f"config key {key} looks like an outside endpoint but nothing in the map names {key}"})
    for n in nodes.values():
        p = nodes.get(n.get("parent"))
        if p and n["kind"] == "package" and p["kind"] in ("service", "library"):
            continue   # a package named like its module is the normal case
        if p and n["kind"] == "method" and p["kind"] == "class":
            continue   # a constructor is named like its class (Java, C#, Kotlin secondary ones)
        if p and n.get("name") and p.get("name") and _last_segment(n["name"]) == _last_segment(p["name"]):
            out.append({"id": "name.container", "node": n["id"],
                        "detail": f"{n['id']} is named like its parent {p['id']}"})
    kids: dict[str, list[str]] = {}
    for n in nodes.values():
        if n.get("parent") in nodes:
            kids.setdefault(n["parent"], []).append(n["id"])

    def has_code(nid: str) -> bool:
        return any(nodes[c]["kind"] in ("file", "package") or has_code(c) for c in kids.get(nid, []))

    for n in nodes.values():
        if n["kind"] in ("service", "library") and not has_code(n["id"]) and not n.get("twins"):
            out.append({"id": "module.empty", "node": n["id"],
                        "detail": f"{n['kind']} {n['id']} has no file or package under it"})
    written = (cmap.get("examples") or {}).get("entries", [])
    covered, keyed = {e.get("node") for e in written}, {(e.get("node"), e.get("key")) for e in written}
    entries = examples.entry_points(cmap)
    pinned, retired = len(cmap.get("pins", [])), len(cmap.get("unpinned", []))
    if pinned + retired < (want := min(3, len(entries))):   # pins the user removed still count as written
        out.append({"id": "pin.few", "node": None,
                    "detail": f"{pinned} pins ({retired} unpinned) for {len(entries)} entry points: pin at least "
                              f"{want}"})
    for m, keys in entries.items():
        if m not in covered:
            out.append({"id": "example.missing", "node": m,
                        "detail": f"entry point {m} ({'; '.join(keys) or 'no key'}) has no example"})
        elif missing := [k for k in keys if (m, k) not in keyed]:
            out.append({"id": "example.missing", "node": m,
                        "detail": f"entry point {m} has no example for {'; '.join(missing)} "
                                  f"({len(keys) - len(missing)} of {len(keys)} keys have one)"})
    for p in cmap.get("pins", []):
        if p.get("start") not in nodes:
            out.append({"id": "pin.start-missing", "node": None,
                        "detail": f"pin {p.get('id')} ({p.get('title')}): start {p.get('start')} is not in this map"})
    return out
