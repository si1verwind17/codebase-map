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
            found: list[tuple] = [(m.start(), next(g for g in m.groups() if g)) for m in CREATES.finditer(text)]
            if f.endswith(".py") and "/migrations/" in f:
                app = f.rsplit("/migrations/", 1)[0].rsplit("/", 1)[-1]
                for i, m in enumerate(models := list(DJANGO_MODEL.finditer(text))):
                    end = models[i + 1].start() if i + 1 < len(models) else len(text)
                    opt = DB_TABLE.search(text, m.end(), end)
                    found.append((m.start(), opt.group("table") if opt else f"{app}_{m.group('model').lower()}",
                                  {"model": m.group("model"), "app": f.rsplit("/migrations/", 1)[0]}))
            for at, name, *model in sorted(found, key=lambda x: x[0]):
                if name.lower() not in seen_tables:
                    seen_tables.add(name.lower())
                    defined.append({"file": f, "line": text.count("\n", 0, at) + 1, "table": name, **(model[0] if model else {})})
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


# ORM verbs on an entity class (`Order.objects.filter`, `Document.findByPk`, `Contact::where`): a write when any
# write verb follows the class in the chain, else a read when a read verb does
ORM_WRITES = {"create", "save", "update", "update_all", "delete", "delete_all", "destroy", "destroy_all", "insert",
              "insert_all", "upsert", "bulk_create", "bulk_update", "update_or_create", "get_or_create", "increment",
              "decrement", "truncate", "remove", "create_many", "createMany", "updateMany", "deleteMany", "bulkCreate",
              "findOrCreate", "firstOrCreate", "updateOrCreate", "insertGetId", "forceDelete"}
ORM_READS = {"get", "filter", "filter_by", "all", "first", "last", "find", "find_by", "find_each", "where", "select",
             "query", "count", "exists", "pluck", "find_one", "findOne", "findAll", "findFirst", "findMany",
             "findUnique", "findByPk", "findAndCountAll", "aggregate", "sum", "paginate", "one", "order_by",
             "includes", "joins", "limit", "order", "values", "values_list", "get_or_404", "first_or_404",
             "firstOrFail", "findOrFail", "whereIn", "orderBy", "latest", "exclude", "annotate", "scalar"}
ORM_HOLDERS = {"objects", "query", "unscoped"}   # Django's manager, Flask-SQLAlchemy's query


def orm_access(file_facts: dict[str, dict], nodes: list[dict], defined: list[dict]) -> None:
    """Add a `tables` access fact (`op` read or write) for each call on an entity class whose table is known: the
    class a table fact is defined on, or the Django model a migration creates. One fact per (table, method, op), at
    its first line. `cls.query..`/`self.objects..` inside the entity counts for the entity itself. A class name two
    entities of different tables share names no table; a Ruby or PHP class counts by the naming default only in a
    `models` folder."""
    by_id = {n["id"]: n for n in nodes}
    tables: dict[str, str] = {}   # entity class id -> its table
    for ff in file_facts.values():
        for t in ff.get("tables", []):
            if t.get("kind") == "defined" and by_id.get(t["in"], {}).get("kind") == "class":
                tables[t["in"]] = t["table"]
    for d in defined:
        if d.get("model"):
            for n in nodes:
                if n["kind"] == "class" and n["name"] == d["model"] and (n.get("file") or "").startswith(d["app"] + "/"):
                    tables.setdefault(n["id"], d["table"])
    created = {d["table"] for d in defined}
    for n in nodes:   # Rails and Eloquent name a model's table by default: its class, snake-case, plural
        if n["kind"] == "class" and n.get("lang") in ("ruby", "php") and "models" in (n.get("file") or "").lower().split("/") \
                and (plural := _plural(_snake(n["name"]))) in created:
            tables.setdefault(n["id"], plural)
    named: dict[str, list[str]] = {}
    for cid in tables:
        named.setdefault(by_id[cid]["name"], []).append(cid)
    for f, ff in file_facts.items():
        seen = {(t["table"], t["in"], t.get("op")) for t in ff.get("tables", [])}
        for c in ff["calls"]:
            parts = re.findall(r"[A-Za-z_$][\w$]*", re.sub(r"\([^()]*\)", "", c["callee"]))
            cid, rest = None, []
            for i, p in enumerate(parts):   # one entity by that name, or several that are one table (a reopened class)
                if len({tables[x] for x in named.get(p, [])}) == 1:
                    cid, rest = named[p][0], parts[i + 1:]
                    break
            if cid is None and len(parts) > 2 and parts[0] in ("cls", "self", "this", "static") \
                    and parts[1] in ORM_HOLDERS:
                owner = by_id.get(by_id.get(c.get("in") or "", {}).get("parent") or "", {})
                cid, rest = (owner["id"], parts[1:]) if owner.get("id") in tables else (None, [])
            if cid is None:
                continue
            op = "write" if any(p in ORM_WRITES for p in rest) else "read" if any(p in ORM_READS for p in rest) else None
            if op and (key := (tables[cid], c["in"], op)) not in seen:
                seen.add(key)
                ff.setdefault("tables", []).append({"table": tables[cid], "line": c["line"], "in": c["in"],
                                                    "kind": "access", "op": op, "pattern": "orm-call",
                                                    "source": "scanner"})
        writes = {(t["table"], t["in"], t["line"]) for t in ff.get("tables", []) if t.get("op") == "write"}
        if writes:   # `Order.query.filter_by(..).delete()`: the filter on that line is part of the write
            ff["tables"] = [t for t in ff["tables"] if not (t.get("op") == "read"
                                                            and (t["table"], t["in"], t["line"]) in writes)]


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


def _plural(word: str) -> str:
    """English plural as Rails and Laravel make a default table name (the common rules; irregular words aside)."""
    if re.search(r"[^aeiou]y$", word):
        return word[:-1] + "ies"
    if re.search(r"(?:s|x|z|ch|sh)$", word):
        return word + "es"
    return word + "s"
