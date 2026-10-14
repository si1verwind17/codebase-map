"""Language-neutral facts from string literals and imports: SQL, URLs, sinks."""
from __future__ import annotations

import re

SQL_START = re.compile(r"^\s*(select|insert|update|delete|with|merge|create|alter|drop|truncate)\b", re.I)
_IDENT = r'([A-Za-z_"{][\w.{}"]*)'
SQL_WRITE = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from|merge\s+into|truncate(?:\s+table)?"
    r"|create\s+table(?:\s+if\s+not\s+exists)?|alter\s+table|drop\s+table(?:\s+if\s+exists)?)\s+" + _IDENT,
    re.I)
SQL_READ = re.compile(r"\b(?:from|join)\s+" + _IDENT, re.I)
SYSTEM_SCHEMAS = ("information_schema.", "pg_catalog.", "pg_")
SQL_WORDS = {"select", "set", "where", "values", "lateral", "unnest",
             "the", "a", "an", "this", "that", "these", "those", "it", "its", "each"}

URL = re.compile(r"(?:https?|wss?|grpc)://[^\s\"'`<>{}]+|(?<![\w}])/(?:api|v\d+)(?:/[\w{}.:-]*)*|(?<=})/(?:api|v\d+)(?:/[\w{}.:-]*)*")


def _table(name: str) -> str | None:
    name = name.replace('"', "").rstrip(".,;)")
    if not name or name.lower() in SQL_WORDS or name.lower().startswith(SYSTEM_SCHEMAS):
        return None
    return name


def sql_facts(text: str) -> dict | None:
    """Tables a string reads/writes; None unless it starts like SQL and names a table."""
    m = SQL_START.match(text)
    if not m:
        return None
    writes, spans = set(), []
    for w in SQL_WRITE.finditer(text):
        spans.append(w.span())
        if t := _table(w.group(1)):
            writes.add(t)
    reads = set()
    for r in SQL_READ.finditer(text):
        if any(s <= r.start() < e for s, e in spans):
            continue
        if t := _table(r.group(1)):
            reads.add(t)
    if not reads and not writes:
        return None
    return {"verb": m.group(1).lower(), "reads": sorted(reads), "writes": sorted(writes)}


USERINFO = re.compile(r"^([a-z]+://)[^/@\s]+@", re.I)


def redact(text: str) -> str:
    """The same text with every URL literal redacted as url_facts does."""
    for raw, clean in zip(URL.findall(text), url_facts(text)):
        text = text.replace(raw.rstrip(".,;)"), clean, 1)
    return text


def url_facts(text: str) -> list[str]:
    """URL literals without credentials (`user:token@`) or query values (names kept): summary.md must not
    repeat secrets."""
    out = []
    for u in URL.findall(text):
        u = USERINFO.sub(r"\1***@", u.rstrip(".,;)"))
        if "?" in u:
            base, query = u.split("?", 1)
            u = base + "?" + "&".join(p.split("=", 1)[0] + "=…" for p in query.split("&") if p)
        out.append(u)
    return out
