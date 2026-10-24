"""Language-neutral facts from string literals and imports: SQL, URLs, sinks."""
from __future__ import annotations

import re

LABEL = re.compile(r"^\s*(?:[A-Z][a-z]+\s*)+$")   # only Title Case words: a UI label (`Truncate Cells`), no SQL
SQL_START = re.compile(r"^\s*(select|insert|update|delete|with|merge|create|alter|drop|truncate)\b", re.I)
_IDENT = r'([A-Za-z_"{][\w.{}"]*)'
_OBJECT = r"(?:table|index|view|trigger|function|procedure|sequence|schema|type|extension|database)\b"
# the clause each statement needs after its first word: prose that starts with the word ("Update the cart",
# "Create order from cart", "Truncate text to fit") has none
SQL_SHAPE = {
    "select": re.compile(r"select\b[\s\S]*\bfrom\b", re.I),
    "insert": re.compile(r"insert\s+into\s", re.I),
    "update": re.compile(r"update\s+(?:[$#%:]?" + _IDENT + r"|\?)(?:\s+(?:as\s+)?\w+)?\s+set\b", re.I),
    "delete": re.compile(r"delete\s+from\s", re.I),
    "with": re.compile(r"with\s+(?:recursive\s+)?\w+\s*(?:\([^()]*\))?\s+as\s*(?:(?:not\s+)?materialized\s*)?\(",
                       re.I),
    "merge": re.compile(r"merge\s+into\s", re.I),
    "create": re.compile(r"create\s+(?:or\s+replace\s+)?(?:(?:global\s+|local\s+)?(?:temp|temporary)\s+|unique\s+"
                         r"|materialized\s+|unlogged\s+)?" + _OBJECT, re.I),
    "alter": re.compile(r"alter\s+" + _OBJECT, re.I),
    "drop": re.compile(r"drop\s+" + _OBJECT, re.I),
    "truncate": re.compile(r"truncate\s+(?:table\s+)?" + _IDENT + r"\s*(?:$|[;,)]|(?:cascade|restrict|restart|continue)\b)",
                           re.I),
}
PROSE = re.compile(r"\.\s*$|\.\s+[A-Z]")   # a sentence ends: SQL never does
SQL_WRITE = re.compile(
    r"\b(?:insert\s+into|delete\s+from|merge\s+into|truncate(?:\s+table)?"
    r"|create\s+table(?:\s+if\s+not\s+exists)?|alter\s+table|drop\s+table(?:\s+if\s+exists)?)\s+" + _IDENT
    + r"|\bupdate\s+" + _IDENT + r"(?=(?:\s+(?:as\s+)?\w+)?\s+set\b)",   # not `FOR UPDATE SKIP LOCKED`
    re.I)
SQL_READ = re.compile(r"\b(?:from|join)\s+" + _IDENT, re.I)
NOT_A_READ = re.compile(r"(?:\(\s*[\w.']+|\bdistinct)\s+$", re.I)   # `extract(epoch from x)`, `a is distinct from b`
CTE = re.compile(r"(?:\bwith\s+(?:recursive\s+)?|,\s*)(\w+)\s*(?:\([^()]*\))?\s+as\s*(?:(?:not\s+)?materialized\s*)?\(",
                 re.I)
SYSTEM_SCHEMAS = ("information_schema.", "pg_catalog.", "pg_")
# what fills a table name in at run time (`{x}`, `${x}`, `#{x}`, `%s`, `%(x)s`, `?`, `:x`): a name holding or cut off
# by one is no table
INTERPOLATION = re.compile(r"[{$#%?]|:\w")
FILLED_IN_TABLE = re.compile(r"\b(?:from|join|into|update|table)\s+(?:[\w.\"]*(?:[{$#%?]|:\w)|$)", re.I)
# never a table unless quoted: SQL keywords that can follow FROM/JOIN/INTO/UPDATE, and the words prose puts there
SQL_WORDS = {"select", "set", "where", "values", "lateral", "unnest", "all", "any", "only", "on", "as", "using",
             "limit", "offset", "skip", "locked", "nowait", "group", "order", "by", "having", "union", "into", "table",
             "and", "or", "not", "null", "in", "is", "exists", "distinct", "returning", "default", "inner", "outer",
             "left", "right", "full", "cross", "natural", "join", "from", "with", "when", "then", "else", "end",
             "the", "a", "an", "this", "that", "these", "those", "it", "its", "each"}

URL = re.compile(r"(?:https?|wss?|grpc)://[^\s\"'`<>{}]+|(?<![\w}])/(?:api|v\d+)(?:/[\w{}.:-]*)*|(?<=})/(?:api|v\d+)(?:/[\w{}.:-]*)*")


def _table(name: str, rest: str = "") -> str | None:
    if INTERPOLATION.match(rest) or "{" in name:
        return None
    quoted = name.startswith('"')
    name = name.replace('"', "").rstrip(".,;)")
    if not name or (not quoted and name.lower() in SQL_WORDS) or name.lower().startswith(SYSTEM_SCHEMAS):
        return None
    return name


def sql_facts(text: str) -> dict | None:
    """Tables a string reads/writes; None unless it is shaped like a SQL statement (its first word followed by the
    clause that word needs, no sentence end) and names a table or fills one in at run time (then with no tables). A
    CTE's name is no table."""
    m = SQL_START.match(text)
    if not m or not SQL_SHAPE[m.group(1).lower()].match(text.lstrip()) or PROSE.search(text) or LABEL.match(text):
        return None
    ctes = {c.lower() for c in CTE.findall(text)}
    writes, spans = set(), []
    for w in SQL_WRITE.finditer(text):
        spans.append(w.span())
        g = 1 if w.group(1) else 2
        if (t := _table(w.group(g), text[w.end(g):])) and t.lower() not in ctes:
            writes.add(t)
    reads = set()
    for r in SQL_READ.finditer(text):
        if any(s <= r.start() < e for s, e in spans) or NOT_A_READ.search(text, 0, r.start()):
            continue
        if (t := _table(r.group(1), text[r.end():])) and t.lower() not in ctes:
            reads.add(t)
    if not reads and not writes and not FILLED_IN_TABLE.search(text):
        return None
    return {"verb": m.group(1).lower(), "reads": sorted(reads), "writes": sorted(writes)}


# calls that print or write text, and calls that reach a database: a scope with the first and none of the second
# writes its SQL out as text (a seed or migration file), it does not run it
OUTPUT_CALLS = {"print", "println", "printf", "print_r", "puts", "write", "writeln", "writelines", "writestring",
                "fprintf", "fprintln", "fprint", "console.log"}
DB_CALL = re.compile(r"exec|query|fetch|prepare|sql|raw|select|batchupdate|^update$|^run$|^copy", re.I)


def text_output_scopes(calls: list[dict]) -> set:
    """The `in` of every scope that writes text out and calls nothing that could reach a database."""
    out, db = set(), set()
    for c in calls:
        last = re.split(r"\.|::|->", c["callee"])[-1].strip()
        if last.lower() in OUTPUT_CALLS or c["callee"].strip().lower() in OUTPUT_CALLS:
            out.add(c["in"])
        elif DB_CALL.search(last):
            db.add(c["in"])
    return out - db



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
