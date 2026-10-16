#!/usr/bin/env python3
"""Draft an issue for the skill's maintainers from OUT/feedback.md, and open it in GitHub's new-issue form.

Usage: feedback.py preview REPO [--out-dir docs/viz-code] [--allow TERM ...]
       feedback.py send REPO --digest DIGEST [--out-dir docs/viz-code] [--allow TERM ...]

OUT/feedback.md is written by the agent with the user: a `# title` line, then what happened, in general terms.
`preview` prints the whole issue exactly as it would go out — that text, then map facts this script adds (counts and
the skill's own names only, never a name, path or value from the repository) — then every word in the text that
matches a name from the user's map. It exits 1 while such words remain; `--allow` passes one the user has read and
accepted. `send` takes the digest `preview` printed, so only the text the user saw can go out, and opens GitHub's
new-issue form filled with it. Nothing is posted: the user reads it there and submits it, or closes the tab.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import platform
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.parse
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vizcode import RULES_VERSION, SCANNER_VERSION, SCHEMA_VERSION, findings, gitsrc, mapcheck  # noqa: E402

ISSUES = "https://github.com/si1verwind17/codebase-map/issues/new"
URL_LIMIT = 8000   # GitHub answers a longer new-issue link with an error page
SKILL_DIR = Path(__file__).resolve().parent.parent
MIN_TERM = 3
LIBRARY_FACTS = ("calls", "imports")   # scanner facts that mostly name a library's API
COMMON_MIN = 5   # shorter common words (`map`, `task`) are noise to the reader
JOIN = 3   # up to this many words in a row are also read as one name: `order repo` is `OrderRepo`


def _class(*cats: str) -> str:
    """A regex class of every character in these Unicode categories: Python's \\w leaves out combining marks, which
    split Thai or Hindi words."""
    out, start = [], None
    for c in range(sys.maxunicode + 2):
        hit = c <= sys.maxunicode and unicodedata.category(chr(c))[0] in cats
        if hit and start is None:
            start = c
        elif not hit and start is not None:
            out.append(re.escape(chr(start)) + ("-" + re.escape(chr(c - 1)) if c - 1 > start else ""))
            start = None
    return "".join(out)


LETTER = _class("L", "M")
ALNUM = _class("L", "M", "N")
WORD = re.compile(f"[{LETTER}][{ALNUM}]*")   # letters of any script, then letters or digits
SEGMENT = re.compile(f"[{ALNUM}][{ALNUM}_-]*")
TOKEN = re.compile(f"[{ALNUM}][{ALNUM}_./:#$-]*")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
LIMIT_LINE = re.compile(r"^- ([a-z]+\.[a-z-]+) · ")
CRASH = re.compile(r"^- drawing check ([a-z]+\.[a-z-]+) crashed")


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _counts(c: collections.Counter) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(c.items(), key=lambda kv: (-kv[1], str(kv[0])))) or "none"


def _section(md: str, title: str) -> list[str]:
    m = re.search(rf"^## {re.escape(title)}\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return [ln for ln in m.group(1).splitlines() if ln.startswith("- ")] if m else []


def facts(out: Path) -> list[str]:
    """The map facts: versions, counts, and names the skill itself defines (node and relation kinds, warning and
    check ids, built-in and pack pattern names). Free text from the map, its paths and its names never go in."""
    node = shutil.which("node")
    lines = [f"- skill: scanner {SCANNER_VERSION}, schema {SCHEMA_VERSION}, rules {RULES_VERSION}",
             f"- system: {platform.system()}, Python {platform.python_version()}, "
             f"Node {'yes' if node else 'not found'}"]
    cmap = _read_json(out / "code-map.json")
    if not isinstance(cmap, dict):
        return lines + ["- map: none yet (scanned, not assembled)"]
    meta = cmap.get("meta") or {}
    nodes, rels = cmap.get("nodes") or [], cmap.get("relations") or []
    lines += [
        f"- map: made by scanner {meta.get('scanner_version', '?')}, schema {meta.get('schema_version', '?')}, "
        f"rules {meta.get('rules_version', '?')}; languages {', '.join(meta.get('languages') or []) or 'none'}",
        f"- nodes: {_counts(collections.Counter(n.get('kind') for n in nodes))}",
        f"- relations: {_counts(collections.Counter(r.get('kind') for r in rels))}",
        f"- relation confidence: {_counts(collections.Counter(r.get('confidence', 'unset') for r in rels))}",
        f"- pins {len(cmap.get('pins') or [])}, examples "
        f"{len((cmap.get('examples') or {}).get('entries') or [])} entries + "
        f"{len((cmap.get('examples') or {}).get('types') or {})} types, problems {len(cmap.get('problems') or [])}",
    ]
    structure = _read_json(out / "structure.json")
    if isinstance(structure, dict):
        stats = structure.get("stats") or {}
        lines.append("- scan: " + ", ".join(f"{k} {stats[k]}" for k in ("files", "modules", "classes", "methods",
                                                                        "parse_errors") if k in stats))
        mods = collections.Counter(m.get("build") for m in structure.get("modules") or [] if isinstance(m, dict))
        if mods:
            lines.append(f"- modules by build: {_counts(mods)}")
        st = structure.get("stack") or {}
        if "unrecognised" in st:
            pats = st.get("patterns") or []
            known = [f"{p['lang']} {p['name']} {p['matches']}" for p in pats if p.get("source") in ("built in", "pack")]
            own = [p for p in pats if p.get("source") == "stack.yaml"]
            lines.append(f"- stack: {len(st['unrecognised'])} unrecognised imports, "
                         f"{len(st.get('servers_without_routes') or [])} server libraries without routes, "
                         f"{len(own)} stack.yaml patterns ({sum(1 for p in own if not p.get('matches'))} "
                         f"with no match)")
            if known:
                lines.append(f"- skill patterns matched: {', '.join(known)}")
    try:
        warns = mapcheck.warnings(cmap, _read(out / "summary.md"))
        cycles = len(findings.cycles(cmap))
    except Exception as e:   # noqa: BLE001 — a broken check is itself worth reporting
        warns, cycles = [{"id": "audit.error"}], 0
        lines.append(f"- content checks failed: {type(e).__name__}")
    lines.append(f"- content warnings: {_counts(collections.Counter(w['id'] for w in warns))}; cycles {cycles}")
    audit = _read(out / "audit.md")
    if audit is not None:
        drawn = re.search(r"^Drawing checks: (\d+) run on (\d+) floors, (\d+) failed, (\d+) accepted", audit, re.M)
        lines.append("- drawing checks: " + (f"{drawn[1]} run on {drawn[2]} floors, {drawn[3]} failed, "
                                             f"{drawn[4]} accepted" if drawn else "skipped"))
        limits = collections.Counter(m[1] for ln in _section(audit, "Map limits") if (m := LIMIT_LINE.match(ln)))
        if limits:
            lines.append(f"- map limits: {_counts(limits)}")
        errors = _section(audit, "Audit errors")
        if errors:
            crashed = collections.Counter(m[1] for ln in errors if (m := CRASH.match(ln)))
            lines.append(f"- audit errors: {len(errors)}" + (f" (crashed: {_counts(crashed)})" if crashed else ""))
    return lines


def _parts(name: str) -> set[str]:
    """A name and its pieces: `db.bay_events`, `bay_events`, `bay`, `events`; `ReservationService`, `Reservation`,
    `Service`."""
    out = {name, *SEGMENT.findall(name)}
    for w in WORD.findall(name):
        out.add(w)
        out.update(CAMEL.findall(w))
    return out


def _plain(part: str) -> bool:
    """One word: `orders`, not `OrderRepo` or `bay_events`."""
    return part.isalpha() and len(CAMEL.findall(part)) == 1


def _vocabulary() -> tuple[set[str], set[str]]:
    """(words, known names) of the skill's own documents and packs (words also of its scanner's code). A map name
    that is one of those words is a common word. A known name is a compound one written there in lower case as a whole (`fastapi` for `FastAPI`,
    `python-package`, `uses-code`): a library or one of the format's own kinds; it and its pieces are left out. Examples in CamelCase (`PgOrderRepo`) are
    not known names: a repository can have the same one."""
    text = " ".join(_read(SKILL_DIR / f) or "" for f in ("SKILL.md", "format.md", "feedback.md"))
    for p in (SKILL_DIR / "scripts" / "vizcode" / "packs").glob("*.yaml"):
        text += " " + (_read(p) or "")
    words = text
    for p in (SKILL_DIR / "scripts" / "vizcode").rglob("*.py"):   # the scanner's words: `insert`, `execute`, `decorator`
        words += " " + (_read(p) or "")
    known = {t for t in TOKEN.findall(text) + SEGMENT.findall(text) if t == t.lower()}
    return {w.lower() for w in WORD.findall(words)}, {t.strip("./:#$-") for t in known}


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def _strings(value) -> list[str]:
    """Every key and string inside an example value."""
    if isinstance(value, dict):
        return [str(k) for k in value] + [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return [value] if isinstance(value, str) else []


def _values(value) -> list[str]:
    """Every string value inside a scanner fact (not its keys: those are the format's own words)."""
    if isinstance(value, dict):
        return [s for v in value.values() for s in _values(v)]
    if isinstance(value, list):
        return [s for v in value for s in _values(v)]
    return [value] if isinstance(value, str) else []


def private_terms(repo: Path, out: Path) -> tuple[dict[str, str], dict[str, str]]:
    """(names, common words), each term (lower case) -> the map name it comes from. Terms come from every node and
    file name, relation key and stack entry in the map, every committed path, the repository's folder and its
    remotes, and their pieces.
    A single word the skill's own documents use is a common word: shown to the user, never blocking. So is a single
    word of a call or an import, mostly a library's API (`execute`): the repository's own methods and modules are
    nodes, and an import no pack knows is in the stack's unrecognised list. A compound name is a name even when
    they use it."""
    names: list[str] = [repo.resolve().name, *_git(repo, "ls-files").splitlines()]   # every committed path
    library: list[str] = []
    names += [t for t in _git(repo, "remote", "-v").split() if "/" in t or ":" in t]
    cmap = _read_json(out / "code-map.json")
    if isinstance(cmap, dict):
        meta = cmap.get("meta") or {}
        names += [str(meta.get("repo") or ""), str(meta.get("root") or "")]
        for n in cmap.get("nodes") or []:
            names += [str(n.get("id") or ""), str(n.get("name") or "")]
        names += [str(r.get("key") or "") for r in cmap.get("relations") or []]
        names += list((cmap.get("files") or {}).keys())
        names += _strings(cmap.get("examples") or {})   # field names and values come from the repository's types
    structure = _read_json(out / "structure.json")
    if isinstance(structure, dict):   # the scanner's facts: there before the map, and finer than it
        names += [v for k in ("nodes", "modules", "relations") for v in _values(structure.get(k))]
        for facts in (structure.get("facts") or {}).values():
            if isinstance(facts, dict):
                names += [v for k, f in facts.items() if k not in LIBRARY_FACTS for v in _values(f)]
                library += [v for k in LIBRARY_FACTS for v in _values(facts.get(k))]
        st = structure.get("stack") or {}
        names += [str(u.get("prefix") or "") for u in st.get("unrecognised") or []]
        names += [str(p.get("name") or "") for p in st.get("patterns") or [] if p.get("source") == "stack.yaml"]
    stack_yaml = _read(out / "stack.yaml") or ""
    names += re.findall(r"prefix:\s*([^,}\s]+)", stack_yaml)
    vocab, known = _vocabulary()
    terms: dict[str, str] = {}
    common: dict[str, str] = {}
    for name in filter(None, names + library):
        parts = _parts(name)
        lib = name in library and name not in names
        skip = {x.lower() for part in parts if not _plain(part) and part.lower() in known for x in _parts(part)}
        for part in parts:
            low = part.lower()
            if len(low) < MIN_TERM or low.isdigit() or low in skip:
                continue
            if _plain(part) and (low in vocab or lib):
                if len(low) >= COMMON_MIN:
                    common.setdefault(low, name)
            else:
                terms.setdefault(low, name)
    return terms, common


TEMPLATE = "send-feedback.yml"   # .github/ISSUE_TEMPLATE/ in the skill's repository: labels the issue
FIELDS = (("report", "What happened"), ("facts", "Map facts"))   # the form's field ids and labels, in order


def compose(out: Path) -> tuple[str, str, str]:
    """(title, the user's text, the map facts) of the issue from OUT/feedback.md and the scan. Only the title and
    the user's text are checked for names: the facts are this script's own."""
    if not (out / "code-map.json").is_file() and not (out / "structure.json").is_file():
        raise ValueError(f"no scan in {out} (code-map.json or structure.json): without one the text cannot be "
                         "checked for the repository's names. Scan first (SKILL.md step 1)")
    text = _read(out / "feedback.md")
    if text is None:
        raise ValueError(f"{out / 'feedback.md'} not found: write it first (a `# title` line, then what happened)")
    lines = [ln for ln in text.strip().splitlines() if not ln.startswith("<!--")]
    if not lines or not lines[0].startswith("# ") or not lines[0][2:].strip():
        raise ValueError("feedback.md must start with a `# title` line")
    title, body = lines[0][2:].strip(), "\n".join(lines[1:]).strip()
    if not body:
        raise ValueError("feedback.md has a title but no text under it")
    return f"[feedback] {title}", body, "\n".join(facts(out))


def rendered(text: str, facts_md: str) -> str:
    """The issue's body as GitHub writes it from the form: each field under its label as a `###` heading."""
    return "\n\n".join(f"### {label}\n\n{value}" for (_, label), value in zip(FIELDS, (text, facts_md))) + "\n"


def _compact(term: str) -> str:
    return re.sub(r"[_./:#$-]", "", term)


def leaks(title: str, body: str, terms: dict[str, str], allowed: set[str]) -> list[tuple[str, str]]:
    """(words in the issue, map name they match) for each word of the issue that is a term, and each run of up to
    JOIN words that spells a compound term (`order repo`, `bay events`), unless allowed."""
    text = title + "\n" + body
    hits: dict[str, str] = {}
    for w in TOKEN.findall(text):
        for part in _parts(w):
            low = part.lower()
            if low in terms and low not in allowed:
                hits.setdefault(low, terms[low])
    joined = {_compact(t): t for t in terms if len(_compact(t)) >= 6}   # shorter ones join by chance: `in to`
    words = [w.lower() for w in WORD.findall(text)]
    for n in range(2, JOIN + 1):
        for i in range(len(words) - n + 1):
            said = " ".join(words[i:i + n])
            if (t := joined.get("".join(words[i:i + n]))) and t not in allowed and said not in allowed:
                hits.setdefault(said, terms[t])
    return sorted(hits.items())


def digest(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()[:12]


def issue_url(title: str, text: str, facts_md: str) -> str:
    """GitHub's new-issue link, the skill's feedback form filled in."""
    fields = {fid: value for (fid, _), value in zip(FIELDS, (text, facts_md))}
    return f"{ISSUES}?{urllib.parse.urlencode({'template': TEMPLATE, 'title': title, **fields})}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["preview", "send"])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--out-dir", default="docs/viz-code")
    ap.add_argument("--allow", action="append", default=[], help="a word the user read and accepted")
    ap.add_argument("--digest", help="send: the digest preview printed")
    a = ap.parse_args(argv)
    try:
        out = a.repo / gitsrc.rel_out_dir(a.repo, a.out_dir)
        title, text, facts_md = compose(out)
    except ValueError as e:
        print(f"feedback: {e}", file=sys.stderr)
        return 2
    allowed = {w.lower() for w in a.allow}
    terms, common = private_terms(a.repo, out)
    hits = leaks(title, text, terms, allowed)
    seen = [(w, src) for w, src in leaks(title, text, common, allowed) if w not in dict(hits)]
    body = rendered(text, facts_md)
    url = issue_url(title, text, facts_md)
    d = digest(title, body)
    if a.command == "preview":
        print("Show the user everything from `Title:` to `Digest:` in a code block, unchanged and in full, before "
              "asking to open it.\n")
        print(f"Title: {title}\n\n{body}")
        print(f"---\nDigest: {d}    Link length: {len(url)} of {URL_LIMIT}")
        if hits:
            print(f"Words that match names from this repository's map ({len(hits)}):")
            print("\n".join(f"- {w} (from {src})" for w, src in hits))
        if seen:
            print(f"Common words that are also names in this repository's map ({len(seen)}; not blocking, for "
                  "the user's review):")
            print("\n".join(f"- {w} (from {src})" for w, src in seen))
        if len(url) > URL_LIMIT:
            print("Too long for a new-issue link: shorten the text.")
        return 1 if hits or len(url) > URL_LIMIT else 0
    if a.digest != d:
        print("feedback: the issue differs from the one previewed (or no --digest): preview it again and show "
              "the user", file=sys.stderr)
        return 1
    if hits:
        print("feedback: words match names from this repository's map: " + ", ".join(w for w, _ in hits),
              file=sys.stderr)
        return 1
    if len(url) > URL_LIMIT:
        print("feedback: too long for a new-issue link: shorten the text", file=sys.stderr)
        return 1
    opened = webbrowser.open(url)
    print(("Opened" if opened else "Could not open a browser; open") + " GitHub's new-issue form, filled in. "
          "Nothing is posted until you press Submit there.")
    if not opened:
        print(url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
