"""Incremental rescan: what changed since the stamped commit, and which facts went stale."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from . import SCANNER_VERSION, SCHEMA_VERSION, examples, gitsrc, rules
from .adapters import SOURCE_SUFFIXES  # noqa: F401  (diff.py reads it from here)
from .assemble import SEMANTIC_KINDS, languages
from .modules import BUILD_FILES

# build files of packs/modules.yaml too: a `*` stays within the file name
DEPLOYABLE_FILES = re.compile(
    r"(^|/)((docker-)?compose[^/]*\.ya?ml|Dockerfile[^/]*|build\.sbt|pyproject\.toml|setup\.py|setup\.cfg|"
    + "|".join(re.escape(f).replace(r"\*", "[^/]*") for f in BUILD_FILES) + ")$")
FULL_RATIO = 0.3


def plan(repo: Path, cmap: dict, structure: dict, out_dir: str) -> tuple[dict, dict | None, dict | None]:
    """Return (stale report, kept meaning, previous meaning). An incremental plan keeps the meaning
    (stale facts flagged); a full one returns None for it and the previous map's facts projected the
    same way, for the agent to check against the new structure (meaning.previous.json)."""
    old, new = cmap["meta"]["commit"], structure["meta"]["commit"]
    report = {"mode": "incremental", "reason": None, "from_commit": old, "to_commit": new,
              "changed": [], "stale_relations": [], "stale_nodes": [], "stale_examples": [], "removed_nodes": []}
    same_root = cmap["meta"].get("root") == structure["meta"].get("root")
    paths: set[str] | None = None   # None: what changed is unknown, so every evidence file counts as changed
    if same_root and gitsrc.commit_exists(repo, old):
        prefix = out_dir.strip("/") + "/"
        changed = [c for c in gitsrc.changed_files(repo, old, new) if not c["path"].startswith(prefix)]
        report["changed"] = changed
        paths = {c["path"] for c in changed} | {c["old_path"] for c in changed if "old_path" in c}

    def full(reason: str):
        report.update(mode="full", reason=reason)
        return report, None, project(cmap, structure, paths)[0]

    if not same_root:
        return full(f"the scanned folder changed ({cmap['meta'].get('root') or 'top level'} → "
                    f"{structure['meta'].get('root') or 'top level'})")
    if (cmap["meta"]["schema_version"], cmap["meta"]["scanner_version"]) != (SCHEMA_VERSION, SCANNER_VERSION):
        return full("scanner or schema version changed")
    if cmap["meta"].get("stack") != (structure.get("stack") or {}).get("digest"):
        return full("stack.yaml changed since the map was made")
    # files in a language the map was made without did not change, so an incremental plan would never reach them
    if new_langs := sorted(set(languages(structure)) - set(cmap["meta"].get("languages", []))):
        return full(f"new languages scanned: {', '.join(new_langs)}")
    behind = rules.behind(cmap, rules.CHANGES.read_text(encoding="utf-8"))
    if behind and behind["recheck"] is None:
        paths = None   # no list to follow, so every fact with evidence is flagged for the full re-check
        return full(f"map made under rules {behind['from']}, older than the oldest entry in CHANGES.md "
                    f"({behind['floor']}): re-check every fact")
    if paths is None:
        return full(f"stamped commit {old[:12]} no longer exists (history rewritten)")
    if any(DEPLOYABLE_FILES.search(p) for p in paths):
        return full("deployable definitions changed (compose/Dockerfile/build files)")
    # only files the scan reads count (tests and excluded paths do not), and a rename counts once
    scanned = set(structure["files"]) | {n["file"] for n in cmap["nodes"] if n.get("file")}
    sources = [c for c in report["changed"] if c["path"] in scanned or c.get("old_path") in scanned]
    if structure["files"] and len(sources) / len(structure["files"]) > FULL_RATIO:
        return full(f"more than {int(FULL_RATIO * 100)}% of source files changed")

    meaning, stale = project(cmap, structure, paths)
    report["removed_nodes"] = stale["removed"]
    report["stale_relations"] = [{k: v for k, v in r.items() if k != "stale"} for r in meaning["relations"] if r.get("stale")]
    report["stale_nodes"] = stale["nodes"]
    report["stale_examples"] = stale["examples"]
    return report, meaning, None


def project(cmap: dict, structure: dict, paths: set[str] | None) -> tuple[dict, dict]:
    """The committed map's facts as a meaning.json, with `"stale": true` on each fact that a removed
    node or a changed evidence file (`paths`; None = every file) makes suspect. Returns (meaning,
    {"removed": removed node ids, "nodes": stale semantic node ids,
    "examples": the examples flagged})."""
    old = cmap["meta"]["commit"]

    def touched(f: str | None) -> bool:
        return f is not None and (paths is None or f in paths)

    new_ids = {n["id"] for n in structure["nodes"]}
    structural = [n for n in cmap["nodes"] if n["kind"] not in SEMANTIC_KINDS]
    removed = sorted(n["id"] for n in structural if n["id"] not in new_ids)
    gone = set(removed)

    runtime = [r for r in cmap["relations"] if r["kind"] not in ("uses-code", "calls")]  # scanner-derived
    stale = {r["id"] for r in runtime
             if any(touched(e["file"]) for e in r["evidence"]) or {r["from"], r["to"], r.get("via")} & gone}
    stale_keys = {r["key"] for r in runtime if r["id"] in stale and r.get("key")}
    stale |= {r["id"] for r in runtime if r.get("key") in stale_keys}

    stale_nodes = {n["id"] for n in cmap["nodes"] if n["kind"] in SEMANTIC_KINDS and not n.get("defaulted")
                   and any(touched(e["file"]) for e in n.get("evidence", []))}

    # an example is stale when its class or handler is gone, or its fingerprint differs against the new structure;
    # flagging works on copies, so the committed map's objects are never mutated
    exs, stale_examples = examples.flag_stale(copy.deepcopy(cmap.get("examples")),
                                              {n["id"]: n for n in structure["nodes"]})

    kept_problems = [p for p in cmap["problems"] if p.get("source") not in ("assemble", "diff")]
    if removed:
        kept_problems.append({"text": f"{len(removed)} node(s) removed since {old[:12]}; comments anchored to them are orphaned",
                              "nodes": [], "removed": removed, "source": "diff"})
    meaning = {
        "domain_context": cmap["meta"]["domain_context"],
        # defaulted libraries are re-derived (and re-reported) by assemble until the agent claims the module
        "nodes": [{**n, "stale": True} if n["id"] in stale_nodes else n
                  for n in cmap["nodes"] if n["kind"] in SEMANTIC_KINDS and not n.get("defaulted")],
        # stale facts stay, flagged: assemble refuses them until each is kept, changed or dropped
        "relations": [{**r, "stale": True} if r["id"] in stale else r for r in runtime],
        # pins and examples carry over (copied); examples are flagged against the new structure
        "pins": copy.deepcopy(cmap.get("pins", [])),
        "unpinned": copy.deepcopy(cmap.get("unpinned", [])),
        "examples": exs,
        "problems": kept_problems,
        "roles": {n["id"]: {"role": n["role"], "why": n["role_why"]} for n in cmap["nodes"]
                  if n.get("role_why") and n["id"] in new_ids},   # a removed package takes its override with it
        "summaries": {n["id"]: n["summary"] for n in structural
                      if "summary" in n and n["id"] in new_ids and not touched(n.get("file"))},
    }
    return meaning, {"removed": removed, "nodes": sorted(stale_nodes), "examples": stale_examples}
