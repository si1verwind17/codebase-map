#!/usr/bin/env python3
"""Write the field guide's tiny example maps: one code-map.json per pattern, in viewer/guide/maps.

Usage: guide_maps.py [--out DIR]
Each example is a small hand-written structure and meaning run through the skill's own pipeline
(`assemble`, then `mapcheck`), so the guide's pictures come from real maps. The output is committed and
deterministic: running it twice gives the same bytes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "visualizing-codebases" / "scripts"))

from vizcode import SCHEMA_VERSION, mapcheck  # noqa: E402
from vizcode.assemble import assemble  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "guide" / "maps"
COMMIT = "0" * 39 + "1"
SCANNED_AT = "2026-10-08T00:00:00Z"
COMPOSE = "compose.yaml"


class Code:
    """A hand-written structure pass: Python modules, packages, files, classes and methods, plus the facts
    `assemble` reads (routes and sinks for package roles, call sites for `calls`)."""

    def __init__(self, repo: str) -> None:
        self.repo = repo
        self.modules: list[dict] = []
        self.nodes: list[dict] = []
        self.relations: list[dict] = []
        self.files: dict[str, dict] = {}
        self.facts: dict[str, dict] = {}
        self._path: dict[str, str] = {}    # node id -> source file
        self._lines: dict[str, int] = {}   # source file -> last line used

    def _line(self, path: str) -> int:
        self._lines[path] = self._lines.get(path, 0) + 2
        return self._lines[path]

    def module(self, path: str) -> str:
        self.modules.append({"id": f"mod:{path}", "path": path, "lang": "python", "build": "python-package"})
        return path

    def package(self, mod: str, name: str) -> str:
        pid = f"{mod}::{name}/"
        self.nodes.append({"id": pid, "kind": "package", "parent": f"mod:{mod}", "name": name, "lang": "python",
                           "file": f"{mod}/{name.replace('.', '/')}", "line": 1, "visibility": "public", "metrics": {}})
        return pid

    def file(self, pkg: str, name: str, route: tuple[str, str] | None = None, sink: str | None = None) -> str:
        """A module file in `pkg`; `route` (method, path) marks it an entry, `sink` (`sql-db`, `http-out`, ...) a
        storage or outbound file. A route's handler is the file's first method."""
        mod, pkg_name = pkg[:-1].split("::")
        dotted = f"{pkg_name}.{name}"
        fid, path = f"{mod}::{dotted}", f"{mod}/{dotted.replace('.', '/')}.py"
        self.nodes.append({"id": fid, "kind": "file", "parent": pkg, "name": f"{name}.py", "lang": "python",
                           "file": path, "line": 1, "visibility": "public", "metrics": {"loc": 20}})
        self.files[path] = {"lang": "python", "module": f"mod:{mod}", "node": fid, "parse_error": False}
        self.facts[path] = {k: [] for k in ("imports", "routes", "sql", "urls", "sinks", "env_keys", "calls",
                                            "includes", "clients", "grpc", "dags", "workflows", "reference_tasks")}
        if route:
            self.facts[path]["routes"].append({"method": route[0], "path": route[1], "handler": None, "line": 3,
                                               "framework": "fastapi"})
            self.facts[path]["sinks"].append({"kind": "http-in", "lib": "fastapi", "line": 1})
        if sink:
            self.facts[path]["sinks"].append({"kind": sink, "lib": "client", "line": 1})
        self._path[fid] = path
        return fid

    def cls(self, owner: str, name: str, implements: list[str] | None = None,
            fields: tuple[tuple[str, str | None], ...] | None = None) -> str:
        path = self._path[owner]
        cid = f"{owner}.{name}"
        node = {"id": cid, "kind": "class", "parent": owner, "name": name, "lang": "python", "file": path,
                "line": self._line(path), "visibility": "public", "metrics": {"loc": 10}}
        if implements:
            node["implements"] = implements
        if fields is not None:
            node["fields"] = [{"name": n, "type": t} for n, t in fields]
        self.nodes.append(node)
        self._path[cid] = path
        return cid

    def method(self, owner: str, name: str, params: tuple[tuple[str, str], ...] = (), returns: str = "None",
               refs: dict[str, list[str]] | None = None, returns_refs: list[str] | None = None) -> str:
        path = self._path[owner]
        mid = f"{owner}#{name}/{len(params)}"
        sig = {"params": [{"name": n, "type": t, **({"refs": refs[n]} if refs and n in refs else {})}
                          for n, t in params], "returns": returns}
        if returns_refs:
            sig["returns_refs"] = returns_refs
        self.nodes.append({"id": mid, "kind": "method", "parent": owner, "name": name, "lang": "python",
                           "file": path, "line": self._line(path), "visibility": "public", "metrics": {"loc": 6},
                           "signature": sig})
        for r in self.facts[path]["routes"]:
            r["handler"] = r["handler"] or mid
        if name == "__init__":   # what builds its class, as the scanner marks it (constructors.mark)
            next(n for n in self.nodes if n["id"] == owner)["ctor"] = {"method": mid}
        self._path[mid] = path
        return mid

    def call(self, caller: str, callee: str, args: int = 0) -> None:
        """A call site in `caller`; `assemble` resolves it to a `calls` relation by name."""
        path = self._path[caller]
        self.facts[path]["calls"].append({"callee": callee, "in": caller, "line": self._line(path), "args": args})

    def uses(self, frm: str, to: str) -> None:
        self.relations.append({"id": f"r:uses-code:mod:{frm}->mod:{to}:", "kind": "uses-code", "from": f"mod:{frm}",
                               "to": f"mod:{to}", "key": None, "confidence": "confirmed",
                               "evidence": [{"file": f"{frm}/requirements.txt", "line": 1}]})

    def structure(self) -> dict:
        return {"meta": {"schema_version": SCHEMA_VERSION, "scanner_version": "guide", "repo": self.repo, "root": None,
                         "commit": COMMIT},
                "modules": self.modules, "nodes": self.nodes, "relations": self.relations, "files": self.files,
                "facts": self.facts, "proto": [], "unassigned": [], "skipped": [], "excluded": [], "stats": {}}


def ev(file: str, line: int = 1) -> list[dict]:
    return [{"file": file, "line": line}]


def service(name: str, line: int, **extra) -> dict:
    return {"id": f"svc:{name}", "kind": "service", "name": name, "modules": [name], "evidence": ev(COMPOSE, line),
            **extra}


def rel(kind: str, frm: str, to: str, key: str, file: str, **extra) -> dict:
    return {"kind": kind, "from": frm, "to": to, "key": key, "confidence": "confirmed", "evidence": ev(file),
            **extra}


def endpoint(code: Code, name: str, handler: str, route: tuple[str, str] = ("POST", "/v1/run"),
             params: tuple[tuple[str, str], ...] = (("body", "dict"),), returns: str = "dict") -> str:
    """A service module with one entry package `api`, one file `routes.py` and its handler: the smallest
    service a line can end at. Returns the handler's id."""
    pkg = code.package(code.module(name), "api")
    return code.method(code.file(pkg, "routes", route=route), handler, params, returns)


# ---------------------------------------------------------------- the examples
def floors() -> tuple[dict, dict]:
    """Two services, one opened: orders' floor has a few packages joined by calls."""
    c = Code("floors")
    c.module("orders")
    api = c.file(c.package("orders", "api"), "routes", route=("POST", "/v1/orders"))
    place = c.method(api, "place_order", (("body", "dict"),), "dict")
    logic = c.file(c.package("orders", "core"), "orders")
    create = c.method(logic, "create", (("order", "dict"),), "dict")
    price = c.file(c.package("orders", "pricing"), "prices")
    total = c.method(price, "total", (("order", "dict"),), "int")
    store = c.file(c.package("orders", "store"), "repo", sink="sql-db")
    save = c.method(store, "save", (("order", "dict"),))
    out = c.file(c.package("orders", "clients"), "billing", sink="http-out")
    bill = c.method(out, "bill", (("order", "dict"),))
    c.call(place, "create", 1)
    c.call(create, "total", 1)
    c.call(create, "save", 1)
    c.call(create, "bill", 1)
    invoice = endpoint(c, "billing", "create_invoice")
    meaning = {"nodes": [service("orders", 2), service("billing", 3)],
               "relations": [rel("request", bill, invoice, "POST /v1/run", "orders/clients/billing.py", data="forward")]}
    return c.structure(), meaning


def codes() -> tuple[dict, dict]:
    """One service with packages, files, a class and a method, so every code letter shows."""
    c = Code("codes")
    c.module("orders")
    api = c.file(c.package("orders", "api"), "routes", route=("POST", "/v1/orders"))
    place = c.method(api, "place_order", (("body", "dict"),), "dict")
    core = c.package("orders", "core")
    svc_file = c.file(core, "service")
    klass = c.cls(svc_file, "OrderService")
    create = c.method(klass, "create", (("order", "dict"),), "dict")
    check = c.method(klass, "check", (("order", "dict"),), "bool")
    rules = c.file(core, "rules")
    limit = c.method(rules, "limit_for", (("customer", "str"),), "int")
    c.call(place, "create", 1)
    c.call(create, "self.check", 1)
    c.call(check, "limit_for", 1)
    return c.structure(), {"nodes": [service("orders", 2)], "relations": []}


def belt() -> tuple[dict, dict]:
    """A one-way request (orders posts to billing) and a two-way one (billing asks payments and gets an answer)."""
    c = Code("belt")
    submit = endpoint(c, "orders", "submit")
    invoice = endpoint(c, "billing", "create_invoice")
    status = endpoint(c, "payments", "status", ("GET", "/v1/payments/{id}"), (("id", "str"),))
    meaning = {"nodes": [service("orders", 2), service("billing", 3), service("payments", 4)],
               "relations": [rel("request", submit, invoice, "POST /v1/invoices", "orders/api/routes.py",
                                 data="forward"),
                             rel("request", invoice, status, "GET /v1/payments/{id}", "billing/api/routes.py",
                                 data="both")]}
    return c.structure(), meaning


def splitters() -> tuple[dict, dict]:
    """orders calls three services (one trunk splits three ways); the three call reports (three merge into one)."""
    c = Code("splitters")
    place = endpoint(c, "orders", "place_order")
    middle = {name: endpoint(c, name, "handle") for name in ("billing", "payments", "shipping")}
    report = endpoint(c, "reports", "record")
    rels = []
    for name, handler in middle.items():
        rels.append(rel("request", place, handler, f"POST /v1/{name}", "orders/api/routes.py", data="forward"))
        rels.append(rel("request", handler, report, "POST /v1/reports", f"{name}/api/routes.py", data="forward"))
    nodes = [service("orders", 2), *(service(n, i) for i, n in enumerate(middle, 3)), service("reports", 6)]
    return c.structure(), {"nodes": nodes, "relations": rels}


def pipe() -> tuple[dict, dict]:
    """Two services joined by a stream."""
    c = Code("pipe")
    send = endpoint(c, "orders", "watch")
    feed = endpoint(c, "tracking", "stream", ("GET", "/v1/track"))
    meaning = {"nodes": [service("orders", 2), service("tracking", 3)],
               "relations": [rel("stream", send, feed, "grpc tracking.v1.Tracking/Watch", "orders/api/routes.py",
                                 data="forward")]}
    return c.structure(), meaning


TOPIC = "topic:events:order-events"


def drones() -> tuple[dict, dict]:
    """One producer, one topic, two consumers (each its own group, each gets a copy)."""
    c = Code("drones")
    place = endpoint(c, "orders", "place_order")
    bill = endpoint(c, "billing", "on_order")
    rep = endpoint(c, "reports", "on_order")
    meaning = {"nodes": [service("orders", 2), service("billing", 3), service("reports", 4),
                         {"id": TOPIC, "kind": "topic", "name": "order-events", "delivery": "fan-out",
                          "evidence": ev("deploy/topics.yaml", 2)}],
               "relations": [rel("event", place, TOPIC, "order-events", "orders/api/routes.py"),
                             rel("event", TOPIC, bill, "order-events", "billing/api/routes.py", group="billing"),
                             rel("event", TOPIC, rep, "order-events", "reports/api/routes.py", group="reports")]}
    return c.structure(), meaning


def queues() -> tuple[dict, dict]:
    """A work queue two workers take from, and the dead-letter topic one of them sends failures to."""
    c = Code("queues")
    place = endpoint(c, "orders", "place_order")
    bill = endpoint(c, "billing", "take")
    pay = endpoint(c, "payments", "take")
    work, dead = "topic:events:invoices", "topic:events:invoices-dead"
    meaning = {"nodes": [service("orders", 2), service("billing", 3), service("payments", 4),
                         {"id": work, "kind": "topic", "name": "invoices", "delivery": "queue",
                          "evidence": ev("deploy/queues.yaml", 2)},
                         {"id": dead, "kind": "topic", "name": "invoices-dead", "delivery": "queue",
                          "dead_letter_of": work, "evidence": ev("deploy/queues.yaml", 6)}],
               "relations": [rel("event", place, work, "invoices", "orders/api/routes.py"),
                             rel("event", work, bill, "invoices", "billing/api/routes.py"),
                             rel("event", work, pay, "invoices", "payments/api/routes.py"),
                             rel("event", bill, dead, "invoices-dead", "billing/api/routes.py", on_failure=True)]}
    return c.structure(), meaning


def in_process() -> tuple[dict, dict]:
    """One service's own queue: two routes put work on it, a background worker in another package takes it off and
    calls out. No call joins them: the hand-offs do (on the service's floor, never on the site)."""
    c = Code("in_process")
    api = c.file(c.package(c.module("orders"), "api"), "routes", route=("POST", "/v1/orders"))
    place = c.method(api, "place_order", (("body", "dict"),), "dict")
    cancel = c.method(api, "cancel_order", (("body", "dict"),), "dict")
    drain = c.method(c.file(c.package("orders", "workers"), "outbox", sink="http-out"), "drain")
    q = "inq:orders:outbox"
    meaning = {"nodes": [service("orders", 2), {"id": "3p:mailer", "kind": "external", "name": "mailer"},
                         {"id": q, "kind": "in-process-queue", "parent": "svc:orders", "name": "outbox",
                          "delivery": "queue", "evidence": ev("orders/app.py", 4)}],
               "relations": [rel("hand-off", place, q, None, "orders/api/routes.py"),
                             rel("hand-off", cancel, q, None, "orders/api/routes.py"),
                             rel("hand-off", q, drain, None, "orders/workers/outbox.py"),
                             rel("ext-call", drain, "3p:mailer", "POST /send", "orders/workers/outbox.py")]}
    return c.structure(), meaning


def push_pull() -> tuple[dict, dict]:
    """A push subscription (billing's receiving dock, its sign naming the endpoint the push calls: the relation's
    key is that path) and a pull subscription (reports, three replicas)."""
    c = Code("push_pull")
    place = endpoint(c, "orders", "place_order")
    bill = endpoint(c, "billing", "on_order", ("POST", "/events"))
    rep = endpoint(c, "reports", "poll")
    meaning = {"nodes": [service("orders", 2), service("billing", 3),
                         service("reports", 4, replicas=3),
                         {"id": TOPIC, "kind": "topic", "name": "order-events", "delivery": "fan-out",
                          "evidence": ev("deploy/topics.yaml", 2)}],
               "relations": [rel("event", place, TOPIC, "order-events", "orders/api/routes.py"),
                             rel("event", TOPIC, bill, "POST /events", "deploy/topics.yaml", subscription="push",
                                 group="orders-billing"),
                             rel("event", TOPIC, rep, "order-events", "deploy/topics.yaml", subscription="pull",
                                 group="orders-reports")]}
    return c.structure(), meaning


def rail() -> tuple[dict, dict]:
    """A nightly job that writes to billing: its yard, billing's station and the schedule sign."""
    c = Code("rail")
    c.module("jobs")
    nightly = c.method(c.file(c.package("jobs", "dags"), "nightly"), "nightly_invoices")
    run = endpoint(c, "billing", "close_day", ("POST", "/v1/close"))
    meaning = {"nodes": [service("jobs", 2), service("billing", 3)],
               "relations": [rel("batch", "svc:jobs", run, "task close_day", "jobs/dags/nightly.py",
                                 schedule=["0 2 * * *"], job="nightly_invoices")]}
    return c.structure(), meaning


def storage() -> tuple[dict, dict]:
    """orders reads and writes its database, keeps a cache only it uses, and writes files to a bucket; reports only
    reads the database. orders also calls billing and reports: a line two rows tall leaves the room beside orders
    the viewer needs to stand the cache as a chest (with orders alone it keeps a lane)."""
    c = Code("storage")
    c.module("orders")
    api = c.file(c.package("orders", "api"), "routes", route=("POST", "/v1/orders"))
    place = c.method(api, "place_order", (("body", "dict"),), "dict")
    store = c.package("orders", "store")
    repo = c.file(store, "repo", sink="sql-db")
    save, find = c.method(repo, "save", (("order", "dict"),)), c.method(repo, "find", (("id", "str"),), "dict")
    cache = c.file(store, "cache", sink="cache")
    get, put = c.method(cache, "get", (("id", "str"),), "dict"), c.method(cache, "put", (("order", "dict"),))
    files = c.file(store, "receipts", sink="cloud-sdk")
    upload = c.method(files, "upload", (("order", "dict"),))
    for callee in ("get", "find", "put", "save", "upload"):
        c.call(place, callee, 1)
    daily = endpoint(c, "reports", "daily", ("GET", "/v1/daily"), ())
    invoice = endpoint(c, "billing", "create_invoice")
    db, kv, bucket = "db:sql:DB_URL", "db:kv:CACHE_URL", "db:blob:RECEIPTS_BUCKET"
    table = f"{db}/public.orders"
    meaning = {"nodes": [service("orders", 2), service("reports", 3), service("billing", 4),
                         {"id": db, "kind": "datastore", "name": "orders-db"},
                         {"id": table, "kind": "table", "parent": db, "name": "public.orders"},
                         {"id": kv, "kind": "datastore", "name": "cache", "store": "cache",
                          "evidence": ev("orders/store/cache.py", 1)},
                         {"id": bucket, "kind": "datastore", "name": "receipts"}],
               "relations": [rel("db-write", save, table, "table public.orders", "orders/store/repo.py"),
                             rel("db-read", find, table, "table public.orders", "orders/store/repo.py"),
                             rel("db-read", get, kv, "cache orders", "orders/store/cache.py"),
                             rel("db-write", put, kv, "cache orders", "orders/store/cache.py"),
                             rel("db-write", upload, bucket, "bucket receipts", "orders/store/receipts.py"),
                             rel("db-read", daily, table, "table public.orders", "reports/api/routes.py"),
                             rel("request", place, invoice, "POST /v1/run", "orders/api/routes.py", data="forward"),
                             rel("request", place, daily, "GET /v1/daily", "orders/api/routes.py", data="forward")]}
    return c.structure(), meaning


def outside() -> tuple[dict, dict]:
    """orders calls an outside tax service; a payment provider posts a webhook to billing; mail is an outside
    service three services call, so it is a utility: a tab on each of them."""
    c = Code("outside")
    place = endpoint(c, "orders", "place_order")
    hook = endpoint(c, "billing", "payment_webhook", ("POST", "/webhooks/payments"))
    rep = endpoint(c, "reports", "send_daily")
    tax, provider, mail = "ext:http:TAX_API_URL", "3p:payment-provider", "3p:mail"
    meaning = {"nodes": [service("orders", 2), service("billing", 3), service("reports", 4),
                         {"id": tax, "kind": "external", "name": "tax-api"},
                         {"id": provider, "kind": "external", "name": "payment-provider"},
                         {"id": mail, "kind": "external", "name": "mail"}],
               "relations": [rel("ext-call", place, tax, "GET /v1/rates", "orders/api/routes.py"),
                             rel("request", provider, hook, "POST /webhooks/payments", "billing/api/routes.py"),
                             rel("ext-call", place, mail, "send", "orders/api/routes.py"),
                             rel("ext-call", hook, mail, "send", "billing/api/routes.py"),
                             rel("ext-call", rep, mail, "send", "reports/api/routes.py")]}
    return c.structure(), meaning


def shared() -> tuple[dict, dict]:
    """A library orders uses: on the shelf at F0, installed inside orders. Inside, a class implements another."""
    c = Code("shared")
    c.module("orders")
    api = c.file(c.package("orders", "api"), "routes", route=("POST", "/v1/orders"))
    place = c.method(api, "place_order", (("body", "dict"),), "dict")
    store = c.file(c.package("orders", "store"), "repo", sink="sql-db")
    base = c.cls(store, "OrderStore")
    c.method(base, "save", (("order", "dict"),))
    impl = c.cls(store, "SqlOrderStore", implements=[base])
    save = c.method(impl, "save", (("order", "dict"),))
    c.module("common")
    retry = c.method(c.file(c.package("common", "common"), "retry"), "with_retry", (("fn", "Callable"),), "Any")
    c.uses("orders", "common")
    c.call(place, "save", 1)
    c.call(save, "with_retry", 1)
    meaning = {"nodes": [service("orders", 2),
                         {"id": "lib:common", "kind": "library", "name": "common", "modules": ["common"]}],
               "relations": []}
    return c.structure(), meaning


def crossings() -> tuple[dict, dict]:
    """Two lines that must cross (one goes under the other), and a line the scan only inferred."""
    c = Code("crossings")
    h = {n: endpoint(c, n, "handle") for n in ("orders", "billing", "payments", "reports")}
    rels = [rel("request", h["orders"], h["billing"], "POST /v1/billing", "orders/api/routes.py"),
            rel("request", h["orders"], h["reports"], "POST /v1/reports", "orders/api/routes.py"),
            rel("request", h["payments"], h["billing"], "POST /v1/billing", "payments/api/routes.py"),
            {**rel("request", h["payments"], h["reports"], "POST /v1/reports", "payments/api/routes.py"),
             "confidence": "inferred", "why": "the URL is read from config; only the path matches"}]
    nodes = [service(n, i) for i, n in enumerate(h, 2)]
    return c.structure(), {"nodes": nodes, "relations": rels}


CALLERS = ("create", "cancel", "refund", "ship", "invoice", "notify", "report", "search")


def layers() -> tuple[dict, dict]:
    """Eight packages of orders all call one `audit` package: a heavily used item, shown in its own layer."""
    c = Code("layers")
    c.module("orders")
    c.method(c.file(c.package("orders", "audit"), "log"), "record", (("event", "str"),))
    for name in CALLERS:
        m = c.method(c.file(c.package("orders", name), "handler"), "run", (("order", "dict"),))
        c.call(m, "record", 1)
    return c.structure(), {"nodes": [service("orders", 2)], "relations": []}


def trace() -> tuple[dict, dict]:
    """orders → billing → payments: billing's create_invoice rounds through the common library and writes its invoices
    table. Two data types with fields and examples, an example per entry point, and one pin."""
    c = Code("trace")
    c.module("orders")
    oapi = c.file(c.package("orders", "api"), "routes", route=("POST", "/v1/orders"))
    order = c.cls(oapi, "Order", fields=(("id", "str"), ("total", "Decimal")))
    place = c.method(oapi, "place_order", (("cart", "dict"),), "Order", returns_refs=[order])
    c.module("billing")
    bapi = c.file(c.package("billing", "api"), "routes", route=("POST", "/v1/invoices"))
    invoice_t = c.cls(bapi, "Invoice", fields=(("id", "str"), ("order_id", "str"), ("amount", "Decimal")))
    create = c.method(bapi, "create_invoice", (("order", "Order"),), "Invoice", refs={"order": [order]},
                      returns_refs=[invoice_t])
    repo = c.file(c.package("billing", "store"), "repo", sink="sql-db")
    save = c.method(repo, "save", (("invoice", "Invoice"),), refs={"invoice": [invoice_t]})
    c.module("common")
    money = c.file(c.package("common", "common"), "money")
    c.method(money, "round_total", (("amount", "Decimal"),), "Decimal")
    c.method(money, "format_total", (("amount", "Decimal"),), "str")
    c.uses("billing", "common")
    c.call(create, "round_total", 1)
    c.call(create, "format_total", 1)
    c.call(create, "save", 1)
    charge = endpoint(c, "payments", "charge", ("POST", "/v1/charges"), (("invoice", "Invoice"),), "dict")
    db = "db:sql:DB_URL"
    table = f"{db}/public.invoices"
    invoice_v = {"id": "inv-7", "order_id": "ord-42", "amount": "24.00"}
    order_v = {"id": "ord-42", "total": "24.00"}
    meaning = {"nodes": [service("orders", 2), service("billing", 3), service("payments", 4),
                         {"id": "lib:common", "kind": "library", "name": "common", "modules": ["common"]},
                         {"id": db, "kind": "datastore", "name": "billing-db"},
                         {"id": table, "kind": "table", "parent": db, "name": "public.invoices"}],
               "relations": [rel("request", place, create, "POST /v1/invoices", "orders/api/routes.py", data="forward"),
                             rel("request", create, charge, "POST /v1/charges", "billing/api/routes.py", data="forward"),
                             rel("db-write", save, table, "table public.invoices", "billing/store/repo.py")],
               "pins": [{"id": "a-customer-pays-for-an-order", "title": "a customer pays for an order", "start": create,
                         "direction": "both", "by": "agent"}],
               "examples": {"types": {order: {"value": order_v}, invoice_t: {"value": invoice_v}},
                            "entries": [{"node": place, "key": "POST /v1/orders", "request": {"cart": ["notebook"]},
                                         "response": order_v},
                                        {"node": create, "key": "POST /v1/invoices", "request": {"order": order_v},
                                         "response": invoice_v},
                                        {"node": charge, "key": "POST /v1/charges", "request": {"invoice": invoice_v},
                                         "response": {"status": "paid"}}]}}
    return c.structure(), meaning


def inspector() -> tuple[dict, dict]:
    """One class with every part the inspector shows for a class: OrderService is built from a repo class, an interface
    (CardGateway implements it) and a library type; CheckoutHandler takes it, and RefundJob takes OrderPort, which it
    implements. Its methods call billing (confirmed) and payments (inferred: the URL is read from config)."""
    c = Code("inspector")
    c.module("orders")
    ports = c.file(c.package("orders", "core"), "ports")
    port = c.cls(ports, "OrderPort")
    gateway = c.cls(ports, "PaymentGateway")
    repo = c.cls(c.file(c.package("orders", "store"), "repo", sink="sql-db"), "OrderRepo")
    c.method(repo, "save", (("order", "dict"),))
    card = c.cls(c.file(c.package("orders", "clients"), "card", sink="http-out"), "CardGateway", implements=[gateway])
    c.method(card, "charge", (("amount", "Decimal"),), "str")
    klass = c.cls(c.file("orders::core/", "service"), "OrderService", implements=[port])
    c.method(klass, "__init__", (("repo", "OrderRepo"), ("gateway", "PaymentGateway"), ("log", "logging.Logger")),
             refs={"repo": [repo], "gateway": [gateway]})
    place = c.method(klass, "place", (("order", "dict"),), "dict")
    cancel = c.method(klass, "cancel", (("order_id", "str"),))
    checkout = c.cls(c.file(c.package("orders", "api"), "checkout"), "CheckoutHandler")
    c.method(checkout, "__init__", (("orders", "OrderService"),), refs={"orders": [klass]})
    refunds = c.cls(c.file(c.package("orders", "jobs"), "refunds"), "RefundJob")
    c.method(refunds, "__init__", (("orders", "OrderPort"),), refs={"orders": [port]})
    invoice = endpoint(c, "billing", "create_invoice", ("POST", "/v1/invoices"))
    refund = endpoint(c, "payments", "refund", ("POST", "/v1/refunds"))
    meaning = {"nodes": [service("orders", 2), service("billing", 3), service("payments", 4)],
               "relations": [rel("request", place, invoice, "POST /v1/invoices", "orders/core/service.py",
                                 data="forward"),
                             {**rel("request", cancel, refund, "POST /v1/refunds", "orders/core/service.py"),
                              "confidence": "inferred", "why": "the URL is read from config; only the path matches"}]}
    return c.structure(), meaning


EXAMPLES = {f.__name__: f for f in (floors, codes, belt, splitters, pipe, drones, queues, in_process, push_pull, rail, storage,
                                    outside, shared, crossings, layers, trace, inspector)}


def build(name: str) -> dict:
    """The example's code map, checked; raises ValueError naming the example when mapcheck fails."""
    structure, meaning = EXAMPLES[name]()
    cmap = assemble(structure, {"domain_context": None, **meaning})
    cmap["meta"]["scanned_at"] = SCANNED_AT   # fixed, so the committed maps are byte-stable
    cmap["meta"].pop("rules_version")   # likewise: a rules bump must not rewrite the guide maps
    cmap["meta"].pop("stack", None)   # and no guide map is made with a stack.yaml
    if errors := mapcheck.check(cmap):
        raise ValueError(f"{name}: " + "; ".join(errors))
    return cmap


def text(cmap: dict) -> str:
    return json.dumps(cmap, indent=1) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    for name in EXAMPLES:
        try:
            cmap = build(name)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        (a.out / f"{name}.code-map.json").write_text(text(cmap), encoding="utf-8")
        print(f"{name}: {json.dumps(mapcheck.stats(cmap)['relations'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
