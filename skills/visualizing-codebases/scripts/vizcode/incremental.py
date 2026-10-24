"""Incremental rescan: what changed since the stamped commit, and which facts went stale."""
from __future__ import annotations

import bisect
import copy
import re
from pathlib import Path

import yaml

from . import SCANNER_VERSION, SCHEMA_VERSION, examples, gitsrc, rules
from .adapters import SOURCE_SUFFIXES  # noqa: F401  (diff.py reads it from here)
from .assemble import SEMANTIC_KINDS, languages
from .modules import BUILD_FILES
from .unscanned import compose_services

# build files of packs/modules.yaml too: a `*` stays within the file name
DEPLOYABLE_FILES = re.compile(
    r"(^|/)((docker-)?compose[^/]*\.ya?ml|Dockerfile[^/]*|build\.sbt|pyproject\.toml|setup\.py|setup\.cfg|"
    + "|".join(re.escape(f).replace(r"\*", "[^/]*") for f in BUILD_FILES) + ")$")
COMPOSE_FILE = re.compile(r"(^|/)(docker-)?compose[^/]*\.ya?ml$")
DOCKERFILE = re.compile(r"(^|/)Dockerfile[^/]*$")
RUN_LINE = re.compile(r"\s*(ENTRYPOINT|CMD)\b", re.I)
FULL_RATIO = 0.3
# a build file inside a test folder, or of a project named as tests (`Orders.UnitTests.csproj`)
TEST_BUILD = re.compile(r"(^|/)(tests?|__tests__|src/test)/|(^|/)[^/]*\.(?:Unit|Integration|Functional)?Tests?\.csproj$")


def _compose_services(text: str | None) -> dict | None:
    """What a compose file says about how each service is built and started: its build context, Dockerfile and
    target, command, entrypoint, and image without the tag or digest (build args and a version bump are not a
    different deployable). None when it does not parse."""
    try:
        doc = yaml.safe_load(text or "")
    except yaml.YAMLError:
        return None
    out = {}
    for name, svc in compose_services(doc).items():
        svc = svc if isinstance(svc, dict) else {}
        image, build = svc.get("image"), svc.get("build")
        if isinstance(image, str):
            head, sep, tail = image.rpartition("/")
            image = head + sep + re.sub(r"(:[^:@]*)?(@.*)?$", "", tail)
        if isinstance(build, dict):
            build = {k: build.get(k) for k in ("context", "dockerfile", "target")}
        out[str(name)] = {"build": build, "image": image, "command": svc.get("command"),
                          "entrypoint": svc.get("entrypoint")}
    return out


def _docker_runs(text: str | None) -> list[str]:
    """A Dockerfile's ENTRYPOINT and CMD instructions, continuation lines joined, spacing normalised."""
    return [" ".join(line.split()) for line in re.sub(r"\\\r?\n", " ", text or "").splitlines() if RUN_LINE.match(line)]


def deployables_changed(repo: Path, old: str, new: str, changed: list[dict]) -> list[str]:
    """Why the changed compose files, Dockerfiles and build files change what is deployed or how modules are found:
    one added, removed or renamed; a compose service added or removed, or its build, image, command or entrypoint
    changed; a Dockerfile's ENTRYPOINT or CMD changed. Edits inside them (dependency versions, environment, build
    steps) are not reasons: the scan reads modules from the new tree anyway."""
    reasons = []
    for c in sorted(changed, key=lambda c: c["path"]):
        path = c["path"]
        if not (DEPLOYABLE_FILES.search(path) or DEPLOYABLE_FILES.search(c.get("old_path", ""))):
            continue
        if all(TEST_BUILD.search(p) for p in (path, c.get("old_path") or path)):
            continue   # a test project's build file (`tests/Basket.UnitTests/*.csproj`): the scan reads none of it
        if c["status"] in "ADR":
            what = {"A": "added", "D": "removed"}.get(c["status"], f"renamed from {c.get('old_path')}")
            reasons.append(f"{path} {what}")
        elif COMPOSE_FILE.search(path):
            before, after = (_compose_services(gitsrc.show(repo, sha, path)) for sha in (old, new))
            if before is None or after is None:
                reasons.append(f"{path}: not readable as YAML")
                continue
            reasons += [f"{path}: service {s} added" for s in after if s not in before]
            reasons += [f"{path}: service {s} removed" for s in before if s not in after]
            reasons += [f"{path}: service {s} {k} changed" for s in before if s in after
                        for k in before[s] if before[s][k] != after[s][k]]
        elif DOCKERFILE.search(path):
            if _docker_runs(gitsrc.show(repo, old, path)) != _docker_runs(gitsrc.show(repo, new, path)):
                reasons.append(f"{path}: ENTRYPOINT/CMD changed")
    return reasons


class Changes:
    """What changed between the map's commit and the new one, by old path and old line. `known` False: nothing
    is known, so every line counts as changed."""

    def __init__(self, changed: list[dict] | None, hunks: dict[str, list[tuple[int, int, int, int]]]):
        self.known = changed is not None
        self.renamed = {c["old_path"]: c["path"] for c in changed or [] if "old_path" in c}
        self.deleted = {c["path"] for c in changed or [] if c["status"] == "D"}
        # changed with no line diff (binary, a type change): the whole file
        self.whole = self.deleted | {c["path"] for c in changed or []
                                     if c["status"] in "MT" and c["path"] not in hunks}
        self.hunks = {f: sorted(h) for f, h in hunks.items()}
        self.lines = {f: sorted(x for a, b, _, _ in h for x in range(a, a + b)) for f, h in self.hunks.items()}
        self.inserts = {f: sorted(a for a, b, _, _ in h if b == 0) for f, h in self.hunks.items()}

    def file(self, f: str | None) -> bool:
        return f is not None and (not self.known or f in self.whole or f in self.hunks)

    def span(self, f: str | None, start: int, end: int) -> bool:
        """Whether any line from start to end (old numbering) changed, or lines were inserted between them."""
        if f is None or not self.known or f in self.whole:
            return f is not None
        lines, inserts = self.lines.get(f, []), self.inserts.get(f, [])
        return (bisect.bisect_left(lines, start) < bisect.bisect_right(lines, end)
                or bisect.bisect_left(inserts, start) < bisect.bisect_left(inserts, end))

    def where(self, f: str, line: int) -> tuple[str, int]:
        """An unchanged line's place in the new commit."""
        shift = sum(d - b for a, b, _, d in self.hunks.get(f, []) if (a + b - 1 if b else a) < line)
        return self.renamed.get(f, f), line + shift


def plan(repo: Path, cmap: dict, structure: dict, out_dir: str) -> tuple[dict, dict | None, dict | None]:
    """Return (stale report, kept meaning, previous meaning). An incremental plan keeps the meaning
    (stale facts flagged); a full one returns None for it and the previous map's facts projected the
    same way, for the agent to check against the new structure (meaning.previous.json)."""
    old, new = cmap["meta"]["commit"], structure["meta"]["commit"]
    report = {"mode": "incremental", "reason": None, "from_commit": old, "to_commit": new,
              "changed": [], "stale_relations": [], "stale_nodes": [], "stale_examples": [], "removed_nodes": [],
              "why": {}, "causes": [], "moved_evidence": 0}
    same_root = cmap["meta"].get("root") == structure["meta"].get("root")
    changes = Changes(None, {})   # what changed is unknown until git says: every evidence line counts as changed
    if same_root and gitsrc.commit_exists(repo, old):
        prefix = out_dir.strip("/") + "/"
        changed = [c for c in gitsrc.changed_files(repo, old, new) if not c["path"].startswith(prefix)]
        report["changed"] = changed
        changes = Changes(changed, {f: h for f, h in gitsrc.changed_lines(repo, old, new).items()
                                    if not f.startswith(prefix)})

    def flagged(meaning: dict, stale: dict) -> dict:
        report["removed_nodes"] = stale["removed"]
        report["stale_relations"] = [{k: v for k, v in r.items() if k != "stale"} for r in meaning["relations"]
                                     if r.get("stale")]
        report["stale_nodes"] = stale["nodes"]
        report["stale_examples"] = stale["examples"]
        report["why"] = stale["why"]
        # the reasons by how many facts each explains: one deleted file is one thing to look at, not 13
        counts: dict[str, int] = {}
        for reasons in stale["why"].values():
            for x in reasons:
                counts[x] = counts.get(x, 0) + 1
        report["causes"] = [{"reason": x, "facts": n} for x, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        report["moved_evidence"] = stale["moved"]
        return meaning

    def full(reason: str):
        report.update(mode="full", reason=reason)
        return report, None, flagged(*project(cmap, structure, changes))

    if not same_root:
        return full(f"the scanned folder changed ({cmap['meta'].get('root') or 'top level'} → "
                    f"{structure['meta'].get('root') or 'top level'})")
    for what, was, now in (("schema", cmap["meta"]["schema_version"], SCHEMA_VERSION),
                           ("scanner", cmap["meta"]["scanner_version"], SCANNER_VERSION)):
        if was != now:   # the scan reads the code differently: ids, nodes and facts can differ everywhere
            return full(f"{what} version changed: {was} → {now}")
    if cmap["meta"].get("stack") != (structure.get("stack") or {}).get("digest"):
        return full("stack.yaml changed since the map was made")
    # files in a language the map was made without did not change, so an incremental plan would never reach them
    if new_langs := sorted(set(languages(structure)) - set(cmap["meta"].get("languages", []))):
        return full(f"new languages scanned: {', '.join(new_langs)}")
    behind = rules.behind(cmap, rules.CHANGES.read_text(encoding="utf-8"))
    if behind and behind["recheck"] is None:
        changes = Changes(None, {})   # no list to follow, so every fact with evidence is flagged for the full re-check
        return full(f"map made under rules {behind['from']}, older than the oldest entry in CHANGES.md "
                    f"({behind['floor']}): re-check every fact")
    if not changes.known:
        return full(f"stamped commit {old[:12]} no longer exists (history rewritten)")
    if deployed := deployables_changed(repo, old, new, report["changed"]):
        return full("deployable definitions changed: " + "; ".join(deployed))
    before, after = ({f["module"] for f in m["files"].values() if f.get("module")} for m in (cmap, structure))
    if before != after:
        return full("modules changed: " + "; ".join(f"{what} {', '.join(sorted(ms))}" for what, ms in
                                                    (("added", after - before), ("removed", before - after)) if ms))
    # only files the scan reads count (tests and excluded paths do not), and a rename counts once
    scanned = set(structure["files"]) | {n["file"] for n in cmap["nodes"] if n.get("file")}
    sources = [c for c in report["changed"] if c["path"] in scanned or c.get("old_path") in scanned]
    if structure["files"] and len(sources) / len(structure["files"]) > FULL_RATIO:
        return full(f"more than {int(FULL_RATIO * 100)}% of source files changed")

    return report, flagged(*project(cmap, structure, changes)), None


def _span(n: dict) -> tuple[int, int] | None:
    loc = (n.get("metrics") or {}).get("loc")
    return (n["line"], n["line"] + loc - 1) if loc and n.get("line") else None


def project(cmap: dict, structure: dict, changes: Changes) -> tuple[dict, dict]:
    """The committed map's facts as a meaning.json, with `"stale": true` on each fact something it depends on made
    suspect: a cited line changed (or the method around it), an end or `via` node is gone or moved to another file,
    or the route its key names changed. Evidence on unchanged lines follows them to their new place. Returns
    (meaning, {"removed": removed node ids, "nodes": stale semantic node ids, "examples": the examples flagged,
    "why": {fact id: [reasons]}, "moved": evidence entries moved})."""
    old = cmap["meta"]["commit"]
    new_nodes = {n["id"]: n for n in structure["nodes"]}
    structural = [n for n in cmap["nodes"] if n["kind"] not in SEMANTIC_KINDS]
    removed = sorted(n["id"] for n in structural if n["id"] not in new_nodes)
    by_id = {n["id"]: n for n in structural}
    methods: dict[str, list[tuple[int, int, str]]] = {}
    for n in structural:
        if n["kind"] == "method" and (span := _span(n)):
            methods.setdefault(n["file"], []).append((*span, n["id"]))

    def cited(e: dict) -> str | None:
        """Why a cited line is suspect: it changed, or the innermost method around it did."""
        f, line = e["file"], e.get("line") or 0
        if not changes.known:
            return "what changed since the map's commit is unknown"
        if f in changes.whole:
            return f"{f} {'deleted' if f in changes.deleted else 'changed'}"
        if changes.span(f, line, line):
            return f"{f}:{line} changed"
        around = [m for m in methods.get(f, []) if m[0] <= line <= m[1]]
        if around and changes.span(f, *(m := min(around, key=lambda m: m[1] - m[0]))[:2]):
            return f"{f}:{line} is in {m[2]}, which changed"
        return None

    def ended(nid: str | None) -> str | None:
        """Why an end or via node is suspect: gone from the new structure, or now in another file."""
        if nid not in by_id:
            return None
        if nid not in new_nodes:
            # the same method with other parameters (`processUpdateForm/1` -> `/2`): the one node it likely became
            heirs = [m for m in new_nodes if "#" in nid and m.rsplit("/", 1)[0] == nid.rsplit("/", 1)[0]
                     and re.sub(r"~\d+$", "", m) != re.sub(r"~\d+$", "", nid)]
            return f"{nid} is not in the new structure" + (f"; now {heirs[0]}?" if len(heirs) == 1 else "")
        was, now = by_id[nid].get("file"), new_nodes[nid].get("file")
        if was and now and changes.renamed.get(was, was) != now:
            return f"{nid} moved from {was} to {now}"
        return None

    def route_keys(files: dict, routes) -> set[tuple[str, str]]:
        return {(f"{r['method'].upper()} {r['path']}", r["handler"]) for f, v in files.items() for r in routes(f, v)
                if isinstance(r.get("handler"), str)}
    gone_routes = (route_keys(cmap["files"], lambda f, v: v.get("routes", []))
                   - route_keys(structure["files"], lambda f, v: structure["facts"].get(f, {}).get("routes", [])))

    why: dict[str, list[str]] = {}
    moved = 0

    def follow(fact: dict, reasons: list[str]) -> dict:
        """A copy of the fact with its unchanged evidence lines at their new place; flagged when reasons."""
        nonlocal moved
        out = dict(fact)
        if "evidence" in fact:
            out["evidence"] = []
            for e in fact["evidence"]:
                if changes.known and e.get("line") and not changes.span(e["file"], e["line"], e["line"]):
                    f, line = changes.where(e["file"], e["line"])
                    moved += (f, line) != (e["file"], e["line"])
                    e = {**e, "file": f, "line": line}
                out["evidence"].append(e)
        if reasons:
            why[fact["id"]] = list(dict.fromkeys(reasons))
            out["stale"] = True
        return out

    runtime = [r for r in cmap["relations"] if r["kind"] not in ("uses-code", "calls")]  # scanner-derived
    def depends(r: dict) -> list[str | None]:
        return [*map(cited, r["evidence"]), *(ended(r.get(k)) for k in ("from", "to", "via")),
                *(f"route {k} of {h} changed" for k, h in sorted(gone_routes) if k == r.get("key"))]
    relations = [follow(r, [x for x in depends(r) if x]) for r in runtime]
    semantic = [follow(n, [x for x in map(cited, n.get("evidence", [])) if x])
                for n in cmap["nodes"] if n["kind"] in SEMANTIC_KINDS and not n.get("defaulted")]
    stale_nodes = [n["id"] for n in semantic if n.get("stale")]

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
        "nodes": semantic,
        # stale facts stay, flagged: assemble refuses them until each is kept, changed or dropped
        "relations": relations,
        # pins and examples carry over (copied); examples are flagged against the new structure
        "pins": copy.deepcopy(cmap.get("pins", [])),
        "unpinned": copy.deepcopy(cmap.get("unpinned", [])),
        "examples": exs,
        "problems": kept_problems,
        "roles": {n["id"]: {"role": n["role"], "why": n["role_why"]} for n in cmap["nodes"]
                  if n.get("role_why") and n["id"] in new_nodes},   # a removed package takes its override with it
        "summaries": {n["id"]: n["summary"] for n in structural
                      if "summary" in n and n["id"] in new_nodes
                      and not (changes.span(n.get("file"), *s) if (s := _span(n)) else changes.file(n.get("file")))},
    }
    return meaning, {"removed": removed, "nodes": sorted(stale_nodes), "examples": stale_examples, "why": why,
                     "moved": moved}
