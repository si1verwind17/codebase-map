"""SQL kept outside the code: a MyBatis mapper's statements (XML), and the tables `.sql` files define.

A mapper file (`<mapper namespace="a.UserMapper">`) holds one statement per interface method, named by its `id`:
its tables are SQL facts of that method, cited at the statement's line. A `.sql` file's `CREATE TABLE` names a
table that exists whatever the code shows (a migration, a schema): listed so a table is never silently missing.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import facts

MAPPER = re.compile(r'<mapper\s+namespace\s*=\s*"([^"]+)"')
STATEMENT = re.compile(r'<(select|insert|update|delete)\b([^>]*)>(.*?)</\1\s*>', re.S | re.I)
STATEMENT_ID = re.compile(r'\bid\s*=\s*"([^"]+)"')
TAG = re.compile(r"<[^>]+>")
CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.S)
ENTITIES = {"&lt;": "<", "&gt;": ">", "&amp;": "&", "&quot;": '"', "&apos;": "'"}
SQL_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.S)
PARAM = re.compile(r"[#$]\{[^}]*\}")
# a schema or migration file of an ORM, by its path, and the table-creating calls in it: Rails and Alembic
# `create_table`, Laravel `Schema::create`, Knex and Sequelize `createTable`, EF Core `CreateTable(name: ..)`,
# Liquibase `<createTable tableName=..>`
SCHEMA_PATH = re.compile(r"(?i)(?:^|/)(?:[^/]*migrat[^/]*|schema\.rb|[^/]*changelog[^/]*|liquibase)(?:/|$)|(?:^|/)schema\.rb$")
# a Django migration's `CreateModel(name="Task", ..)`: table `<app>_<model>` (the app is the folder holding
# `migrations/`), or the model's `db_table` option
DJANGO_MODEL = re.compile(r"""\bCreateModel\(\s*name\s*=\s*["'](?P<model>\w+)["']""")
DB_TABLE = re.compile(r"""["']db_table["']\s*:\s*["'](?P<table>[\w.]+)["']""")
SCHEMA_SUFFIXES = (".rb", ".php", ".py", ".cs", ".js", ".ts", ".xml")
CREATES = re.compile(
    r"""\bcreate_table\s*\(?\s*[:"'](?P<a>\w+)"""
    r"""|\bSchema::create\s*\(\s*["'](?P<b>\w+)"""
    r"""|\bcreateTable\s*\(\s*["'`](?P<c>\w+)"""
    r'|\bCreateTable\s*\(\s*name\s*:\s*"(?P<d>\w+)"'
    r'|<createTable\b[^>]*\btableName\s*=\s*"(?P<e>\w+)"')
CREATE = re.compile(r"(?im)^\s*create\s+(?:or\s+replace\s+)?(?:(?:global|local)\s+)?(?:(?:temporary|temp|unlogged)\s+)?"
                    r"table\s+(?:if\s+not\s+exists\s+)?((?:[`\"\[]?\w+[`\"\]]?\.)?[`\"\[]?\w+[`\"\]]?)")


def _statement_text(raw: str) -> str:
    """A statement's SQL: tags (dynamic `<if>`, `<include>`) dropped and entities decoded outside `<![CDATA[..]]>`
    sections, whose text is kept as written (`a < b`)."""
    def plain(x: str) -> str:
        x = TAG.sub(" ", x)
        for k, v in ENTITIES.items():
            x = x.replace(k, v)
        return x
    parts, pos = [], 0
    for c in CDATA.finditer(raw):
        parts += [plain(raw[pos:c.start()]), c.group(1)]
        pos = c.end()
    return " ".join(parts + [plain(raw[pos:])])


def read(root: Path, tree: list[str], skip) -> tuple[list[dict], list[dict]]:
    """(mapper statements, tables defined in .sql files and in ORM schema or migration files) of the files in `tree`
    that `skip(path)` keeps; a table is listed once, where it is first created."""
    statements, defined = [], []
    seen_tables: set[str] = set()
    for f in tree:
        if skip(f) or not f.endswith((".xml", ".sql", *SCHEMA_SUFFIXES)):
            continue
        text = (root / f).read_text(encoding="utf-8", errors="replace")
        if not f.endswith(".sql") and SCHEMA_PATH.search(f) and not MAPPER.search(text):
            found = [(m.start(), next(g for g in m.groups() if g)) for m in CREATES.finditer(text)]
            if f.endswith(".py") and "/migrations/" in f:
                app = f.rsplit("/migrations/", 1)[0].rsplit("/", 1)[-1]
                for i, m in enumerate(models := list(DJANGO_MODEL.finditer(text))):
                    end = models[i + 1].start() if i + 1 < len(models) else len(text)
                    opt = DB_TABLE.search(text, m.end(), end)
                    found.append((m.start(), opt.group("table") if opt else f"{app}_{m.group('model').lower()}"))
            for at, name in sorted(found):
                if name.lower() not in seen_tables:
                    seen_tables.add(name.lower())
                    defined.append({"file": f, "line": text.count("\n", 0, at) + 1, "table": name})
            continue
        if not f.endswith((".xml", ".sql")):
            continue
        if f.endswith(".sql"):
            plain = SQL_COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)   # same offsets, no comments
            for m in CREATE.finditer(plain):
                name = re.sub(r'[`"\[\]]', "", m.group(1))
                if name.lower() not in seen_tables:
                    seen_tables.add(name.lower())
                    defined.append({"file": f, "line": plain.count("\n", 0, m.start(1)) + 1, "table": name})
            continue
        if not (ns := MAPPER.search(text)):
            continue
        for m in STATEMENT.finditer(text):
            if not (sid := STATEMENT_ID.search(m.group(2))):
                continue
            sql = " ".join(PARAM.sub("?", _statement_text(m.group(3))).split())
            if (q := facts.sql_facts(sql)) is not None:
                statements.append({"namespace": ns.group(1), "id": sid.group(1), "file": f,
                                   "line": text.count("\n", 0, m.start()) + 1, "sql": q})
    return statements, defined


def attach(statements: list[dict], nodes: list[dict], file_facts: dict[str, dict]) -> None:
    """Add each mapper statement's tables to the `sql` facts of the interface method it names."""
    classes = {n["id"].split("::", 1)[-1]: n for n in nodes if n["kind"] == "class"}
    methods: dict[tuple[str, str], dict] = {}
    for n in nodes:
        if n["kind"] == "method":
            methods.setdefault((n.get("parent") or "", n["name"]), n)
    for st in statements:
        cls = classes.get(st["namespace"])
        m = methods.get((cls["id"], st["id"])) if cls else None
        if m is not None and m.get("file") in file_facts:
            file_facts[m["file"]]["sql"].append({**st["sql"], "line": m["line"], "in": m["id"],
                                                 "source": f"{st['file']}:{st['line']}"})
