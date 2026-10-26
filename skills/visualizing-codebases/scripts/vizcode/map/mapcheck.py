"""Checks a code-map: schema, then the rules a schema cannot express."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import jsonschema

from . import examples, pins
from .assemble import default_store

SCHEMA = json.loads((Path(__file__).resolve().parent.parent.parent / "schema" / "code-map.schema.json").read_text(encoding="utf-8"))
RUNTIME_KINDS = {"request", "event", "stream", "batch", "db-read", "db-write", "ext-call"}
STALE_HINT = "stale — re-resolve it: keep it (delete the flag), change it, or drop it"
PARENT_KINDS = {
    "service": {None}, "library": {None}, "datastore": {None}, "external": {None}, "topic": {None},
    "package": {"service", "library"}, "class": {"package", "class", "file"}, "file": {"package"},
    "method": {"class", "file"}, "table": {"datastore"}, "in-process-queue": {"service"},
}
NODE_FIELD_KIND = {"delivery": ("topic", "in-process-queue"), "dead_letter_of": ("topic",), "replicas": ("service",),
                   "store": ("datastore",)}
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
        if n["kind"] == "in-process-queue":
            for field, what in (("delivery", "queue (each item to one consumer) or fan-out (to every subscriber)"),
                                ("evidence", "the line that creates it")):
                if field not in n:
                    errors.append(f"node {n['id']}: in-process-queue needs {field}: {what}")
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
        for field, kinds in NODE_FIELD_KIND.items():
            if field in n and n["kind"] not in kinds:
                errors.append(f"node {n['id']}: {field} belongs on a {' or '.join(kinds)} node, not a {n['kind']} "
                              "— delete it")
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
        if r["kind"] == "hand-off":
            errors += _hand_off_errors(r, nodes, root)
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


def _hand_off_errors(r: dict, nodes: dict[str, dict], root) -> list[str]:
    """A hand-off joins one in-process queue to a method or class of the service that holds the queue."""
    ends = [nodes.get(r[e], {}) for e in ("from", "to")]
    queues = [n for n in ends if n.get("kind") == "in-process-queue"]
    if len(queues) != 1:
        return [f"relation {r['id']}: hand-off must start or end at an in-process-queue node, and only one end"]
    other = ends[1] if queues[0] is ends[0] else ends[0]
    if other and other.get("kind") not in ("method", "class"):
        return [f"relation {r['id']}: hand-off joins a queue to a method (or class), not a {other.get('kind')}"]
    owner = queues[0].get("parent")
    if other and root(other["id"]).get("id") != owner:
        return [f"relation {r['id']}: {other['id']} is not in {owner}, which holds the queue — an in-process queue "
                "never crosses services; when the produce or consume code sits in a library, credit the "
                f"{owner} method that calls it"]
    return []


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
CREDENTIAL_SUFFIXES = ("_TOKEN", "_API_KEY")
# words of a config key that say what kind of address it is, not whose: `ORDER_SERVICE_URL` names `order`
ROLE_WORDS = {"api", "service", "svc", "callback", "base", "endpoint", "server", "client", "ws", "wss", "http",
              "https", "grpc", "internal", "public", "rest", "webhook", "host", "url", "uri"}
WORD = re.compile(r"[a-z0-9]+")
# words of a credential key that say which credential it is, not whose: `DROPBOX_REFRESH_TOKEN` names `dropbox`
CREDENTIAL_WORDS = {"access", "refresh", "secret", "client", "app", "private", "auth", "bearer", "id"}
ENV_LINE = re.compile(r"^- \*\*env keys:\*\* (.*)$", re.M)   # as structure.summary_md writes it
QUEUE_LINE = re.compile(r"^- \*\*in-process queues:\*\* (.*)$", re.M)
QUEUE_SITE = re.compile(r"^(?:queue|fan-out) at (\S+):(\d+) in ")
# a `Likely requests` line of summary.md: the client end's method id
LIKELY_LINE = re.compile(r"^- (?:[A-Z]+ \S+|grpc \S+) ← (\S+) \(([^)]+)\) → ", re.M)   # topic lines: no `request`
COMPOSE_FILE = re.compile(r"(?:^|/)(?:docker-)?compose[\w.-]*\.ya?ml$", re.I)
# a file named in a problem, so the folder holding it counts as named (`docker/web/Dockerfile`, `relay/config.yaml`)
FILE_EXT = r"(?:ya?ml|json|toml|ini|conf|cfg|xml|properties|env|sh|sql|txt|md|js|ts|py|go|rb|php|java|kt|cs|rs|lua|template)"
DEPLOY_LINE = re.compile(r"^- deployable `([^`]+)` \((.*)\) — (.*)$", re.M)


def _last_segment(name: str) -> str:
    return re.split(r"[./:#$]", name.rstrip("$/"))[-1]


def _queues_missing(cmap: dict, summary_md: str) -> list[dict]:
    """A queue creation site the scanner found is accounted for when an in-process-queue cites its line in
    `evidence`, or a `problems` entry names `file:line` (why it is none: one method fills and drains it)."""
    cited = {(e.get("file"), e.get("line")) for n in cmap.get("nodes", []) if n.get("kind") == "in-process-queue"
             for e in n.get("evidence", [])}
    said = " ".join(p.get("text", "") for p in cmap.get("problems", []))
    out = []
    for m in QUEUE_LINE.finditer(summary_md):
        for site in (s.strip() for s in m.group(1).split(";")):
            if (hit := QUEUE_SITE.match(site)) and (hit[1], int(hit[2])) not in cited \
                    and not re.search(rf"{re.escape(hit[1])}:{hit[2]}(?!\d)", said):
                out.append({"id": "queue.missing", "node": None,
                            "detail": f"in-process queue created at {hit[1]}:{hit[2]} is in no in-process-queue "
                                      "node's evidence: add the node and its hand-offs where a trace stops at it, "
                                      "or say in problems why it is none"})
    return out


def _requests_unmatched(cmap: dict, summary_md: str) -> list[dict]:
    """A client call summary.md pairs with a repo route or rpc is accounted for when a request, ext-call or stream
    starts at its method (or names it as `via`), or a `problems` entry names the method or its file:line."""
    if "## Likely requests" not in summary_md:
        return []
    starts = {r.get(k) for r in cmap.get("relations", []) if r.get("kind") in ("request", "ext-call", "stream")
              for k in ("from", "via")}
    said = " ".join(p.get("text", "") for p in cmap.get("problems", []))
    section = summary_md.split("## Likely requests", 1)[1].split("\n## ", 1)[0]
    out, seen = [], set()
    for mid, at in LIKELY_LINE.findall(section):
        if mid in starts or mid in seen or re.search(rf"(?<![\w:#/.]){re.escape(mid)}(?![\w/~])", said) \
                or re.search(rf"(?<![\w/.]){re.escape(at)}(?!\d)", said):
            continue
        seen.add(mid)
        out.append({"id": "request.unmatched", "node": mid,
                    "detail": f"{mid} ({at}) calls a route or rpc of this repo (summary.md § Likely requests) and "
                              "starts no request: write the request to the handler it reaches, an ext-call if it "
                              "goes elsewhere, or say in problems why it is none"})
    return out


def _deployables_unscanned(cmap: dict, summary_md: str) -> list[dict]:
    """A deployable folder whose source is mostly not scanned is accounted for when a service cites a file inside it
    (its Dockerfile) or a line of its compose service, or is named like that compose service, or a `problems` entry
    names the folder or a file directly in it."""
    services = [n for n in cmap.get("nodes", []) if n.get("kind") == "service"]
    cited = {e.get("file", "") for n in services for e in n.get("evidence", [])}
    # a service's deploy line: its first citation of a compose file (a gateway citing another block's `ports:` is none)
    cited_lines = {next(((e.get("file", ""), e.get("line")) for e in n.get("evidence", [])
                         if COMPOSE_FILE.search(str(e.get("file", "")))), None) for n in services} - {None}
    named = {str(n.get("name", "")) for n in services} | {n["id"].removeprefix("svc:") for n in services}
    said = " ".join(p.get("text", "") for p in cmap.get("problems", []))
    out = []
    for folder, how, what in DEPLOY_LINE.findall(summary_md):
        # the repository root holds every file: only its own Dockerfile counts there
        inside = (lambda f: f in re.findall(r"Dockerfile `([^`]+)`", how)) if folder == "." \
            else (lambda f: f.startswith(folder + "/"))
        # the folder, or a file directly in it (`docker/web/Dockerfile`), never a folder below it
        mention = r"`\.`" if folder == "." else \
            rf"(?<![\w./-]){re.escape(folder)}(?:/(?:[\w.-]*\.{FILE_EXT}|Dockerfile[\w.-]*))?(?![\w/-]|\.[\w-])"
        blocks = [(f, int(a), int(b or a))
                  for f, a, b in re.findall(r"compose service `[^`]+` in ([^\s;:]+):(\d+)(?:-(\d+))?", how)]
        if any(inside(f) for f in cited) or named & set(re.findall(r"compose service `([^`]+)`", how)) \
                or any(f == bf and isinstance(n, int) and a <= n <= b for f, n in cited_lines for bf, a, b in blocks) \
                or re.search(mention, said):
            continue
        out.append({"id": "deployable.unscanned", "node": None,
                    "detail": f"deployable `{folder}` ({how}) is mostly source the scanner does not read ({what}): "
                              "model it as a service citing its deploy line, with its relations read from its code "
                              "and config and inferred (not an external), or say in problems why it is none"})
    return out


SETUP_ROUTES = 3   # a handler that registers this many routes itself reads as the function that sets them up


def _route_handlers(cmap: dict, nodes: dict[str, dict]) -> list[dict]:
    """Routes whose handler looks wrong: a file (no entry point: no example, no trace start) or a function that
    registers SETUP_ROUTES or more routes itself and handles some of them. One warning per handler, cleared by a
    `problems` entry naming the handler's id or one of those routes' `file:line`."""
    said = " ".join(p.get("text", "") for p in cmap.get("problems", []))
    out = []
    for f, info in sorted((cmap.get("files") or {}).items()):
        routes = [r for r in info.get("routes", []) if r.get("handler") in nodes]
        mine: dict[str, list[dict]] = {}
        for r in routes:
            mine.setdefault(r["handler"], []).append(r)
        for h, rs in mine.items():
            n = nodes[h]
            if n["kind"] == "method":
                if n.get("file") != f:   # a handler in another file: its lines are not this file's
                    continue
                end =n.get("line", 0) + (n.get("metrics") or {}).get("loc", 1) - 1
                inside = [r for r in routes if n.get("line", 0) <= r["line"] <= end]
                rs = [r for r in rs if r in inside]
                if len(inside) < SETUP_ROUTES or not rs:
                    continue
            elif n["kind"] != "file":
                continue
            sites = [f"{f}:{r['line']}" for r in rs]
            if re.search(rf"(?<![\w.:/#-]){re.escape(h)}(?![\w/#~])", said) \
                    or any(re.search(rf"{re.escape(x)}(?!\d)", said) for x in sites):
                continue
            listed = "; ".join(f"{r['method']} {r['path']} at {x}" for r, x in zip(rs, sites))
            if n["kind"] == "file":
                out.append({"id": "route.file-handler", "node": h,
                            "detail": f"{len(rs)} route{'s' * (len(rs) != 1)} in {f} "
                                      f"{'have' if len(rs) != 1 else 'has'} the file as handler ({listed}): no "
                                      "entry point, so no example or trace "
                                      "starts there. Point each at the function that handles it in stack.yaml (a "
                                      "handler group), or say in problems why the file is right"})
            else:
                out.append({"id": "route.setup-handler", "node": h,
                            "detail": f"{h} registers {len(inside)} routes and is the handler of {len(rs)} of them "
                                      f"({listed}): a function that sets routes up is rarely what handles them. "
                                      "Point each at its real handler in stack.yaml (a handler group), or say in "
                                      "problems why it is right"})
    return out


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
        outside = [n for n in nodes.values() if n["kind"] in ("service", "external")]
        owners = {n.get("name", "").lower() for n in outside if n.get("name")}
        owner_words = [set(WORD.findall(o)) - ROLE_WORDS for o in owners]
        # names run together, so `Last.fm` and `3p:lastfm` both read `lastfm`
        compact = {"".join(WORD.findall(x)) for n in outside
                   for x in (n.get("name", "").lower(), n["id"].split(":")[-1].lower())} - {""}
        seen: set[str] = set()
        for m in ENV_LINE.finditer(summary_md):
            for key in (k.strip() for k in m.group(1).split(";")):
                suffix = next((s for s in EXT_SUFFIXES if key.endswith(s)), None)
                if not suffix or key in seen:
                    continue
                seen.add(key)
                stem = key[:-len(suffix)].lower()
                words = [w for w in WORD.findall(stem) if w not in ROLE_WORDS]
                if suffix in CREDENTIAL_SUFFIXES:
                    words = [w for w in words if w not in CREDENTIAL_WORDS]
                if stem and key.lower() not in named and stem.replace("_", "-") not in owners \
                        and stem not in owners and not (words and any(set(words) <= ow for ow in owner_words)) \
                        and not (words and "".join(words) in compact):
                    out.append({"id": "ext.missing", "node": None,
                                "detail": f"config key {key} looks like an outside endpoint but nothing in the map names {key}"})
        out += _queues_missing(cmap, summary_md)
        out += _deployables_unscanned(cmap, summary_md)
        out += _requests_unmatched(cmap, summary_md)
    for r in cmap.get("relations", []):
        if r.get("kind") in ("request", "ext-call") and r.get("data") == "both":
            out.append({"id": "data.two-way-call", "node": r.get("from"),
                        "detail": f"{r['kind']} {r.get('id') or r['from'] + ' -> ' + r['to']} has data both, which "
                                  "draws a two-way belt as if each end called the other: a reply is not data moving "
                                  "back. Leave it forward, from the caller; a flow both ways is a bidirectional stream"})
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

    # a service the scanner cannot read has no code but relations of its own, read from its config (SKILL.md)
    runtime_ends = {e for r in cmap.get("relations", []) if r["kind"] not in ("uses-code", "calls")
                    for e in (r.get("from"), r.get("to"))}
    said = " ".join(p.get("text", "") for p in cmap.get("problems", []))
    listed = {x for p in cmap.get("problems", []) for x in p.get("nodes", []) or []}
    for n in nodes.values():
        if n["kind"] in ("service", "library") and not has_code(n["id"]) and not n.get("twins") \
                and not (n["kind"] == "service" and n["id"] in runtime_ends) \
                and not (n["kind"] == "service" and (n["id"] in listed
                                                     or re.search(rf"(?<![\w:-]){re.escape(n['id'])}(?![\w-])", said))):
            out.append({"id": "module.empty", "node": n["id"],
                        "detail": f"{n['kind']} {n['id']} has no file or package under it: give it its module, or "
                                  "for a service whose image holds no scanned code (generated or unscanned output), "
                                  "say so in problems naming it"})
    ends = {e for r in cmap.get("relations", []) for e in (r.get("from"), r.get("to"))}
    for n in nodes.values():
        if n["kind"] == "external" and n["id"] not in ends:
            out.append({"id": "external.unused", "node": n["id"],
                        "detail": f"external {n['id']} has no relation: an outside node is on the map only because "
                                  "something talks to it. Add the relation, or drop the node"})
    out += _route_handlers(cmap, nodes)
    written = (cmap.get("examples") or {}).get("entries", [])
    covered, keyed = {e.get("node") for e in written}, {(e.get("node"), e.get("key")) for e in written}
    entries = examples.entry_points(cmap)
    pinned, retired = len(cmap.get("pins", [])), len(cmap.get("unpinned", []))
    if pinned + retired < (want := min(3, len(entries))):   # pins the user removed still count as written
        out.append({"id": "pin.few", "node": None,
                    "detail": f"{pinned} pins ({retired} unpinned) for {len(entries)} entry points: pin at least "
                              f"{want}"})
    for m, keys in examples.required(cmap)[0].items():
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
