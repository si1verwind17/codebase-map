"""A small hand-built code map for the example and pin checks: a route handler calling down a chain, a consumer, a
table reader, and classes with and without fields."""

ORDER = "m::m.models.Order"
LINE = "m::m.models.Line"
RECEIPT = "m::m.models.Receipt"
AUDIT = "m::m.models.AuditRow"
ROW = "m::m.models.Row"
BARE = "m::m.models.Bare"
CREATE = "m::m.api#create/1"
PRICE = "m::m.api#price/1"
TAX = "m::m.api#tax/1"
LOG = "m::m.api#log/1"
CONSUME = "m::m.api#consume/1"
READ = "m::m.api#read/1"
API_FILE = "m::m.api"
TOPIC = "topic:kafka:orders"
TABLE = "db:postgres:DB_HOST/public.orders"


def cls(cid: str, *fields: tuple[str, str]) -> dict:
    node = {"id": cid, "kind": "class", "parent": "m::m.models", "name": cid.rsplit(".", 1)[1]}
    if fields:
        node["fields"] = [{"name": n, "type": t} for n, t in fields]
    return node


def method(mid: str, refs: tuple[str, ...] = (), returns_refs: tuple[str, ...] = ()) -> dict:
    return {"id": mid, "kind": "method", "parent": API_FILE, "name": mid.split("#")[1].split("/")[0],
            "signature": {"params": [{"name": "x", "type": "Any", "refs": list(refs)}], "returns": "Any",
                          "returns_refs": list(returns_refs)}}


def rel(kind: str, frm: str, to: str, key: str | None = None) -> dict:
    return {"id": f"r:{kind}:{frm}->{to}:{key or ''}", "kind": kind, "from": frm, "to": to, "key": key,
            "confidence": "confirmed", "evidence": [{"file": "m/api.py", "line": 1}]}


def cmap() -> dict:
    """A fresh copy (tests change it). create -> price -> tax -> log by calls; the topic feeds consume; read reads
    the table; a request ends at a service; /health's handler is the file node."""
    return {
        "nodes": [
            {"id": "svc:m", "kind": "service", "name": "m"},
            {"id": API_FILE, "kind": "file", "parent": "m::m/", "name": "api.py"},
            cls(ORDER, ("id", "str"), ("total", "float")), cls(LINE, ("sku", "str")), cls(RECEIPT, ("paid", "bool")),
            cls(AUDIT, ("at", "str")), cls(ROW, ("n", "int")), cls(BARE),
            method(CREATE, (ORDER, BARE)), method(PRICE, (LINE,)), method(TAX, returns_refs=(RECEIPT,)),
            method(LOG, (AUDIT,)), method(CONSUME), method(READ, returns_refs=(ROW,)),
            {"id": TOPIC, "kind": "topic", "name": "orders"},
            {"id": TABLE, "kind": "table", "parent": "db:postgres:DB_HOST", "name": "public.orders"},
        ],
        "relations": [rel("calls", CREATE, PRICE), rel("calls", PRICE, TAX), rel("calls", TAX, LOG),
                      rel("event", TOPIC, CONSUME, "orders"), rel("db-read", READ, TABLE, "table public.orders"),
                      rel("request", "svc:m", "svc:m", "GET /nowhere")],
        "files": {"m/api.py": {"lang": "python", "module": "mod:m", "node": API_FILE,
                               "routes": [{"method": "POST", "path": "/orders", "handler": CREATE, "line": 3},
                                          {"method": "GET", "path": "/health", "handler": API_FILE, "line": 9}]}},
        "pins": [{"id": "customer-orders", "title": "customer orders", "start": CREATE, "direction": "downstream",
                  "by": "agent"},
                 {"id": "who-reads-orders", "title": "who reads orders", "start": TABLE, "direction": "upstream",
                  "by": "user"}],
        "unpinned": [],
        "examples": {"types": {}, "entries": []},
    }
