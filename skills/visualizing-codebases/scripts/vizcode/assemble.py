"""structure.json + meaning.json -> code-map.json."""
from __future__ import annotations

import re

import datetime as dt
from pathlib import Path

from . import RULES_VERSION, calls, examples, ids, pins, readme
from .stack import LANGS
from .direction import apply_defaults
from .layout import layout
from .roles import ROLES, package_roles

SEMANTIC_KINDS = {"service", "library", "datastore", "table", "external", "topic", "in-process-queue"}
GITIGNORE = ["structure.json", "summary.md", "meaning.json", "meaning.previous.json", "stale.json",
             "code-map.invalid.json",
             "index.html", "export-comment.md", "audit.md", "feedback.md"]
GITATTRIBUTES = ["code-map.json linguist-generated=true -diff"]   # paths relative to the output folder


def evidence_errors(meaning: dict, read) -> list[str]:
    """Cited lines that cannot be right: a file not in the scanned commit, a line past its end, a blank line.
    `read(path)` is the file's text at that commit, or None."""
    texts: dict[str, list[str] | None] = {}
    out: list[str] = []

    def walk(x, where: str) -> None:
        if isinstance(x, dict):
            for e in x.get("evidence") or [] if isinstance(x.get("evidence"), list) else []:
                if isinstance(e, dict) and isinstance(e.get("file"), str) and isinstance(e.get("line"), int):
                    check(e["file"], e["line"], where)
            for k, v in x.items():
                if k != "evidence":
                    walk(v, where)
        elif isinstance(x, list):
            for v in x:
                walk(v, where)

    def check(f: str, line: int, where: str) -> None:
        if f not in texts:
            text = read(f)
            texts[f] = None if text is None else text.removesuffix("\n").split("\n")   # lines as the scanner counts them
        lines = texts[f]
        if lines is None:
            out.append(f"{where}: evidence {f}:{line}: no such file at the scanned commit")
        elif line < 1 or line > len(lines):
            out.append(f"{where}: evidence {f}:{line} is past the end of the file ({len(lines)} lines)")
        elif not lines[line - 1].strip():
            out.append(f"{where}: evidence {f}:{line} is a blank line: cite the line that shows the fact")

    for group in ("nodes", "relations", "examples", "problems"):
        walk(meaning.get(group), f"meaning.json {group}")
    return out


def meaning_errors(meaning: dict, structure: dict) -> list[str]:
    """Shape problems in the agent's meaning.json, as a fix list (checked before assembling)."""
    errors: list[str] = []
    if not isinstance(meaning, dict):
        return ["meaning.json must be a JSON object"]
    if "flows" in meaning:
        return ["flows: removed from the format — delete it and write pins and examples instead "
                "(SKILL.md § Pinned traces, § Examples)"]
    for key, typ, word in (("nodes", list, "a list"), ("relations", list, "a list"), ("pins", list, "a list"),
                           ("unpinned", list, "a list"), ("examples", dict, "an object"), ("problems", list, "a list"),
                           ("roles", dict, "an object"), ("summaries", dict, "an object")):
        if key in meaning and meaning[key] is not None and not isinstance(meaning[key], typ):
            errors.append(f"{key} must be {word}")
        elif key in meaning and meaning[key] is None:
            errors.append(f"{key} must be {word} (got null)")
    if errors:
        return errors
    for i, p in enumerate(meaning.get("problems", []), 1):
        if not isinstance(p, dict) or not isinstance(p.get("text"), str):
            errors.append(f"problem {i}: must be an object with a text")
    for i, n in enumerate(meaning.get("nodes", []), 1):
        missing = [k for k in ("id", "kind") if not isinstance(n, dict) or not n.get(k)]
        if missing:
            errors.append(f"node {i}: missing {', '.join(missing)}")
    seen: dict[str, int] = {}
    vias: dict[str, str | None] = {}
    for i, r in enumerate(meaning.get("relations", []), 1):
        missing = [k for k in ("kind", "from", "to") if not isinstance(r, dict) or not r.get(k)]
        if missing:
            errors.append(f"relation {i}: missing {', '.join(missing)}")
        elif r["kind"] == "calls":
            errors.append(f"relation {i} ({r['from']} -> {r['to']}): calls are resolved by the scanner; remove it")
        else:
            rid = ids.relation_id(r["kind"], r["from"], r["to"], r.get("key"))
            if rid in seen and r.get("via") and vias[rid] and r.get("via") != vias[rid]:
                errors.append(f"relation {i} duplicates relation {seen[rid]} ({rid}): the same call made by two "
                              f"library methods ({vias[rid]}, {r['via']}) is one relation: keep one `via` and "
                              "merge their evidence, which cites both call sites")
            elif rid in seen:
                errors.append(f"relation {i} duplicates relation {seen[rid]} ({rid}): merge their evidence, "
                              "or tell them apart by key (a job queue: key each enqueue by its job, "
                              "references/interactions.md § Queues in a store or a job system)")
            seen.setdefault(rid, i)
            vias.setdefault(rid, r.get("via"))
    errors += pins.errors(meaning)
    errors += examples.shape_errors(meaning.get("examples") or {})
    packages = {n["id"] for n in structure.get("nodes", []) if n.get("kind") == "package"}
    package_module = {n["id"]: n.get("parent") for n in structure.get("nodes", []) if n.get("kind") == "package"}
    claimed: dict[str, str] = {}
    for n in meaning.get("nodes", []):
        if not isinstance(n, dict) or "packages" not in n:
            continue
        mine = {m if str(m).startswith("mod:") else f"mod:{m}" for m in n.get("modules") or []}
        if n.get("kind") != "service" or not isinstance(n["packages"], list):
            errors.append(f"node {n.get('id')}: packages: a list of package ids, on a service only")
            continue
        for p in n["packages"]:
            if not isinstance(p, str) or p not in packages:
                errors.append(f"node {n['id']}: packages: {p}: no such package (find.py OUT/structure.json NAME "
                              "--kind package)")
            elif package_module[p] not in mine:
                errors.append(f"node {n['id']}: packages: {p} is in {package_module[p]}: list that module in its "
                              "modules too")
            elif p in claimed and claimed[p] != n["id"]:
                errors.append(f"node {n['id']}: packages: {p} is claimed by {claimed[p]} too: one service owns it")
            claimed.setdefault(p, n["id"])
    for pkg, o in (meaning.get("roles") or {}).items():
        if pkg not in packages:
            errors.append(f"role override {pkg}: no such package")
        if not isinstance(o, dict) or o.get("role") not in ROLES:
            errors.append(f"role override {pkg}: role {o.get('role') if isinstance(o, dict) else o!r} is not one of {', '.join(ROLES)}")
        if not isinstance(o, dict) or not o.get("why"):
            errors.append(f"role override {pkg}: needs a why (it is dropped on the next rescan without one)")
    return errors


STORE_BY_ENGINE = {**dict.fromkeys(("redis", "memcached", "valkey", "keydb"), "cache"),
                   **dict.fromkeys(("s3", "gcs", "blob", "minio", "r2"), "bucket"),
                   **dict.fromkeys(("bigquery", "snowflake", "redshift", "clickhouse", "databricks"), "warehouse")}


def default_store(node_id: str) -> str:
    """The `store` of a datastore from the engine segment of `db:<engine>:<key>`; unknown engines are databases."""
    parts = node_id.split(":")
    return STORE_BY_ENGINE.get(parts[1].lower() if len(parts) > 1 else "", "database")


def languages(structure: dict) -> list[str]:
    """The languages a structure scanned (the map's `meta.languages`)."""
    return sorted({m["lang"] for m in structure["modules"]})


def file_entry(info: dict, facts: dict) -> dict:
    """A file's map entry: what structure.json says about it, plus its route facts (method, path, handler, line) when
    it has any with a handler, so the map alone knows every route's handler (entry points, format.md § Files)."""
    out = dict(info)
    routes = [{k: r[k] for k in ("method", "path", "handler", "line")} for r in facts.get("routes", [])
              if isinstance(r.get("handler"), str)]
    if routes:
        out["routes"] = routes
    return out


DEPLOY_FILE = re.compile(r"(?:^|/)(?:(?:docker-)?compose[\w.-]*\.ya?ml|Dockerfile[\w.-]*|Procfile|[\w.-]+\.sh|"
                         r"[\w.-]+\.service|serverless\.ya?ml|app\.ya?ml|fly\.toml|[\w.-]+\.tf)$"
                         r"|(?:^|/)(?:k8s|kubernetes|helm|charts|deploy|deployment|manifests)/", re.I)

def assemble(structure: dict, meaning: dict, previous: dict | None = None) -> dict:
    """`previous` is the last code-map; its layout keeps surviving items where they were."""
    owner: dict[str, str] = {}
    sem_nodes = [{k: v for k, v in n.items() if k != "twins"} for n in meaning.get("nodes", [])]   # twins are re-derived
    for n in sem_nodes:
        if n.get("kind") == "datastore" and "store" not in n:
            n["store"] = default_store(n["id"])
    problems = [p for p in meaning.get("problems", []) if p.get("source") != "assemble"]
    claims: dict[str, list[str]] = {}
    primary: dict[str, list[str]] = {}
    # a service a deploy file runs (compose, a Dockerfile, a registration script, k8s or helm, a unit file), not only
    # a doc line (README) that says to launch it by hand
    deployed = {n["id"]: any(DEPLOY_FILE.search(str(e.get("file", ""))) for e in n.get("evidence", []))
                for n in sem_nodes}
    for n in sem_nodes:
        for i, mpath in enumerate(n.get("modules", [])):
            mid = f"mod:{mpath}" if not mpath.startswith("mod:") else mpath
            claims.setdefault(mid, []).append(n["id"])
            if i == 0:
                primary.setdefault(mid, []).append(n["id"])
    twin_of: dict[str, list[str]] = {}   # module -> the other services that deploy it
    for mid, who in claims.items():
        # a module deployed by several services: its code sits with the service whose primary module it is
        # deterministic: a service that lists it first, else any claimant; among those, one a deploy file runs
        # (compose, a registration script) before one only the docs launch (a hand-run `adhoc`); lowest id breaks
        # ties (meaning order changes after the first rescan, ownership must not)
        cands = primary.get(mid) or who
        owner[mid] = min(cands, key=lambda s: (not deployed.get(s, False), s))
        others = [w for w in who if w != owner[mid]]
        if others:
            twin_of[mid] = others
            problems.append({"text": f"module {mid} is deployed by {owner[mid]} and {', '.join(others)}: its code "
                                     f"sits under {owner[mid]}; {', '.join(others)} show(s) a twin",
                             "nodes": [owner[mid], *others], "source": "assemble"})
    for m in structure["modules"]:
        if m["id"] not in owner:
            key = m["id"].removeprefix("mod:")      # the path, with `#<lang>` for a folder's second language
            lid = f"lib:{key}"
            sem_nodes.append({"id": lid, "kind": "library", "parent": None, "name": m["path"],
                              "lang": m["lang"], "modules": [key], "defaulted": True})
            owner[m["id"]] = lid
            problems.append({"text": f"module {m['path']} not classified as service or library; defaulted to library",
                             "nodes": [lid], "source": "assemble"})

    # packages a service claims (one module building several deployables, Go's `cmd/<svc>` and `internal/<svc>`):
    # each, and every package below it, sits under that service and is no other service's twin
    claims_pkg = {p: n["id"] for n in sem_nodes for p in n.get("packages") or []}

    def claimant(pid: str) -> str | None:
        # a package id ends with `/`; one below it continues its name with `/` (Go) or `.` (JVM, Python)
        hits = [p for p in claims_pkg if pid == p or pid.startswith((p.rstrip("/") + "/", p.rstrip("/") + "."))]
        return claims_pkg[max(hits, key=len)] if hits else None

    summaries = meaning.get("summaries", {})
    nodes = []
    twins: dict[str, list[str]] = {}
    for n in structure["nodes"]:
        n = dict(n)
        by = claimant(n["id"]) if n["kind"] == "package" and claims_pkg else None
        for other in twin_of.get(n["parent"], []) if by is None else []:
            twins.setdefault(other, []).append(n["id"])
        if by is not None:
            n["parent"] = by
        elif n["parent"] in owner:
            n["parent"] = owner[n["parent"]]
        if n["id"] in summaries:
            n["summary"] = summaries[n["id"]]
        nodes.append(n)

    relations: dict[str, dict] = {}
    # a module's code use is each claiming service's too (its packages are part of that module)
    pkg_module = {n["id"]: n["parent"] for n in structure["nodes"] if n["kind"] == "package"}
    claimers: dict[str, set[str]] = {}
    for p, svc in claims_pkg.items():
        claimers.setdefault(pkg_module.get(p, ""), set()).add(svc)
    for r in structure["relations"]:
        to = owner.get(r["to"], r["to"])
        for frm in sorted({owner.get(r["from"], r["from"])} | claimers.get(r["from"], set())):
            if frm == to:
                continue
            rid = ids.relation_id("uses-code", frm, to, None)
            relations.setdefault(rid, {**r, "id": rid, "from": frm, "to": to})
    for r in meaning.get("relations", []):
        r = dict(r)
        r["id"] = ids.relation_id(r["kind"], r["from"], r["to"], r.get("key"))   # from content: an edit renames it
        relations[r["id"]] = r
    apply_defaults(list(relations.values()))

    for n in sem_nodes:
        if n["id"] in twins:
            n["twins"] = twins[n["id"]]
    all_nodes = sorted(sem_nodes, key=lambda n: n["id"]) + nodes
    call_rels, call_problems = calls.resolve(all_nodes, list(relations.values()), structure["facts"])
    for r in call_rels:
        relations.setdefault(r["id"], r)
    problems += call_problems
    overrides = meaning.get("roles", {})
    roles = package_roles(all_nodes, structure["files"], structure["facts"], overrides)
    for n in all_nodes:
        if n["id"] in roles:
            n["role"] = roles[n["id"]]
            if n["id"] in overrides and overrides[n["id"]].get("why"):
                n["role_why"] = overrides[n["id"]]["why"]

    if not structure["files"]:
        problems.append({"text": f"no source files in a supported language ({', '.join(LANGS)}) found at "
                                 f"{structure['meta']['commit'][:12]} "
                                 "(after exclusions): the map has no code", "nodes": [], "source": "assemble"})
    nodes_by_id = {n["id"]: n for n in all_nodes}
    langs = languages(structure)
    cmap = {
        "meta": {"schema_version": structure["meta"]["schema_version"],
                 "scanner_version": structure["meta"]["scanner_version"],
                 "rules_version": RULES_VERSION,
                 "repo": structure["meta"]["repo"], "root": structure["meta"].get("root"),
                 "commit": structure["meta"]["commit"],
                 "scanned_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "languages": langs, "domain_context": meaning.get("domain_context")},
        "nodes": all_nodes,
        "relations": sorted(relations.values(), key=lambda r: r["id"]),
        "pins": [dict(p) for p in meaning.get("pins", [])],
        "unpinned": list(meaning.get("unpinned", [])),
        "examples": examples.stamped(meaning.get("examples"), nodes_by_id),
        "files": {f: file_entry(i, structure.get("facts", {}).get(f, {})) for f, i in structure["files"].items()},
        "problems": problems,
    }
    prev_meta = (previous or {}).get("meta", {})
    prev_layout = (previous or {}).get("layout") if prev_meta.get("schema_version") in (2, 3) else None
    if digest := (structure.get("stack") or {}).get("digest"):
        cmap["meta"]["stack"] = digest
    cmap["layout"] = layout(cmap, roles, prev_layout)
    return cmap


def ensure_repo_files(repo: Path, out_dir: str) -> None:
    """Mark the map generated (hidden from diffs) and keep working files out of git."""
    out = repo / out_dir
    out.mkdir(parents=True, exist_ok=True)
    readme.write(out)
    for name, lines in ((".gitignore", GITIGNORE), (".gitattributes", GITATTRIBUTES)):
        f = out / name
        have = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
        if missing := [g for g in lines if g not in have]:   # keep the user's own lines
            f.write_text("\n".join(have + missing) + "\n", encoding="utf-8")
