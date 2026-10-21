"""The TypeScript and JavaScript built-in packs (imports, NestJS annotated routes, Express/Koa/Fastify regex routes
and mounts, TypeORM/Prisma/Sequelize tables), and the NestJS and Express fixtures mapped with packs only."""
import pytest

from vizcode import stack, structure

from helpers import routes, sinks, tables

API = "apps/api/src"
CTRL = "apps/api::src/orders.orders.controller.OrdersController"


def build(make_repo, files, name="demo"):
    return structure.build(make_repo(files, name=name), "docs/viz-code")


def got_routes(s, f):
    return [(r["method"], r["path"], r["handler"]) for r in s["facts"][f].get("routes", [])]


# NestJS (npm workspaces) with packs only

def test_nest_routes(nest_repo):
    s = structure.build(nest_repo, "docs/viz-code")
    assert [m["id"] for m in s["modules"]] == ["mod:apps/api", "mod:libs/db"]
    assert routes(s, f"{API}/orders/orders.controller.ts") == [
        ("GET", "/orders/{id}", f"{CTRL}#findOne/1", 8, "nestjs", "pack"),
        ("POST", "/orders", f"{CTRL}#create/1", 13, "nestjs", "pack"),
        ("ANY", "/orders/legacy", f"{CTRL}#legacy/0", 18, "nestjs", "pack")]
    for f in ("main.ts", "app.module.ts", "orders/orders.service.ts", "pricing/pricing.client.ts"):
        assert routes(s, f"{API}/{f}") == [], f
    # the global prefix is a mount: listed, composed by the agent
    assert [(m["path"], m["target"], m["line"], m["framework"]) for m in s["facts"][f"{API}/main.ts"]["mounts"]] == [
        ("/api", None, 6, "nestjs-global-prefix")]


def test_nest_sinks_and_tables(nest_repo):
    s = structure.build(nest_repo, "docs/viz-code")
    assert sinks(s, f"{API}/pricing/pricing.client.ts") == [("http-out", "axios")]
    # @nestjs/common is in every service (Injectable): wiring; the server is @nestjs/core, the bootstrap's
    assert sinks(s, f"{API}/orders/orders.controller.ts") == []
    assert sinks(s, f"{API}/orders/orders.service.ts") == [("sql-db", "@nestjs/typeorm"), ("sql-db", "typeorm")]
    assert sinks(s, f"{API}/main.ts") == [("http-in", "@nestjs/core")]
    assert sinks(s, "libs/db/src/order.entity.ts") == [("sql-db", "typeorm")]
    assert tables(s, "libs/db/src/order.entity.ts") == [
        ("orders", 3, "libs/db::src.order.entity.Order", "defined", "typeorm-entity")]
    for f in s["facts"]:
        if f != "libs/db/src/order.entity.ts":
            assert "tables" not in s["facts"][f], f
    # the workspace package `@shop/db` is the repo's own
    assert {(r["from"], r["to"]) for r in s["relations"]} == {("mod:apps/api", "mod:libs/db")}


def test_nest_stack_section(nest_repo):
    s = structure.build(nest_repo, "docs/viz-code")
    assert s["stack"]["unrecognised"] == [] and s["stack"]["servers_without_routes"] == []
    pats = {p["name"]: (p["matches"], p["files"], p.get("form"), p.get("mount")) for p in s["stack"]["patterns"]}
    assert pats["nestjs"] == (3, 1, "annotated", None)
    assert pats["nestjs-global-prefix"] == (1, 1, None, True)
    assert pats["typeorm-entity"][:2] == (1, 1)
    assert "express" not in pats and "fastify" not in pats
    md = structure.summary_md(s)
    assert "## Stack — nothing unrecognised" in md
    assert "- typescript nestjs (pack): 3 routes in 1 file\n" in md
    assert "- **mounts:** /api (apps/api/src/main.ts:6)\n" in md
    assert "- **tables (patterns):** orders (libs/db/src/order.entity.ts:3 defined on" in md


# Express (JavaScript) with packs only

def test_express_routes_and_handlers(express_repo):
    s = structure.build(express_repo, "docs/viz-code")
    # a named last argument resolves to that function in the module; an inline one is the file (its node made)
    assert routes(s, "src/app.js") == [
        ("GET", "/orders", ".::src/handlers.js#listOrders/2", 7, "express", "pack"),
        ("GET", "/orders/{id}", ".::src/handlers.js#getOrder/2", 8, "express", "pack"),
        ("ANY", "/ping", ".::src/app.js", 9, "express", "pack")]
    assert routes(s, "src/v1.js") == [("POST", "/orders", ".::src/v1.js#createOrder/2", 4, "express", "pack")]
    assert routes(s, "src/handlers.js") == []


def test_express_mounts_sinks_tables(express_repo):
    s = structure.build(express_repo, "docs/viz-code")
    assert [(m["path"], m["target"], m["line"], m["framework"]) for m in s["facts"]["src/app.js"]["mounts"]] == [
        ("/v1", "v1", 10, "express-use")]
    assert "mounts" not in s["facts"]["src/v1.js"]
    assert sinks(s, "src/handlers.js") == [("sql-db", "pg")]
    assert sinks(s, "src/app.js") == [("http-in", "express")]
    assert sinks(s, "src/v1.js") == [("http-in", "express")]
    # no table pattern for pg: the tables come from the SQL strings
    assert all("tables" not in f for f in s["facts"].values())
    assert [(q["reads"], q["in"]) for q in s["facts"]["src/handlers.js"]["sql"]] == [
        (["orders"], ".::src/handlers.js#listOrders/2"), (["orders"], ".::src/handlers.js#getOrder/2")]
    assert s["stack"]["unrecognised"] == [] and s["stack"]["servers_without_routes"] == []
    md = structure.summary_md(s)
    assert "- javascript express (pack): 4 routes in 2 files\n" in md
    assert "- javascript express-use (pack): 1 mount in 1 file\n" in md
    assert "- **mounts:** /v1 → v1 (src/app.js:10)\n" in md


def test_express_negatives(make_repo):
    """`map.get("x")`, a one-argument `app.get('title')` (a setting), a template path and a
    member of another name are not routes; nothing matches without the `express` import."""
    src = ("const app = makeApp();\nconst map = new Map();\nmap.get('/x', 1);\napp.get('title');\n"
           "app.get(`/t/${id}`, h);\nmyapp.get('/m', h);\napp.get('/real', h);\napp.use('/v2', r);\n"
           "function h() {}\n")
    s = build(make_repo, {"package.json": '{"name": "x"}\n', "a.js": src})
    f = s["facts"]["a.js"]
    assert not f.get("routes") and not f.get("mounts")
    s = build(make_repo, {"package.json": '{"name": "x"}\n', "a.js": "import express from 'express';\n" + src},
              name="b")
    f = s["facts"]["a.js"]
    assert [(r["method"], r["path"], r["handler"]) for r in f["routes"]] == [("GET", "/real", ".::_root_/a.js#h/0")]
    assert [m["path"] for m in f["mounts"]] == ["/v2"]


def test_express_handler_forms(make_repo):
    src = ("import express from 'express';\nconst router = express.Router();\n"
           "router.get(\n  '/a',\n  auth,\n  orders.listA,\n);\nrouter.put('/b', async (req, res) => {});\n"
           "router.delete('/c/:id', h)\nrouter.patch('/d', [auth], h);\nfunction h() {}\nfunction listA() {}\n")
    s = build(make_repo, {"package.json": '{"name": "x"}\n', "r.ts": src})
    got = [(r["method"], r["path"], r["line"]) for r in s["facts"]["r.ts"]["routes"]]
    assert got == [("GET", "/a", 3), ("PUT", "/b", 8), ("DELETE", "/c/{id}", 9), ("PATCH", "/d", 10)]
    h = {r["path"]: r["handler"] for r in s["facts"]["r.ts"]["routes"]}
    # a multi-line call with a trailing comma; a member name resolves by its last segment
    assert h["/a"] == ".::_root_/r.ts#listA/0" and h["/c/{id}"] == ".::_root_/r.ts#h/0"
    # an inline function, or an array argument (it ends the chain of names): the file
    assert h["/b"] == h["/d"] == ".::_root_/r.ts"


# Koa and Fastify

def test_koa_router(make_repo):
    src = ("const Router = require('@koa/router');\nconst router = new Router({ prefix: '/v1' });\n"
           "router.get('/orders/:id', getOrder);\nrouter.all('/any', getOrder);\nrouter.use('/sub', sub.routes());\n"
           "ctx.cookies.get('x');\nfunction getOrder(ctx) {}\n")
    s = build(make_repo, {"package.json": '{"name": "x"}\n', "k.js": src})
    f = s["facts"]["k.js"]
    assert [(r["method"], r["path"], r["handler"], r["framework"]) for r in f["routes"]] == [
        ("GET", "/v1/orders/{id}", ".::_root_/k.js#getOrder/1", "koa-router"),
        ("ANY", "/v1/any", ".::_root_/k.js#getOrder/1", "koa-router")]
    assert [(m["path"], m["target"], m["framework"]) for m in f["mounts"]] == [
        ("/sub", None, "koa-router-use"), ("/v1", None, "koa-router-prefix")]
    legacy = src.replace("@koa/router", "koa-router")
    s = build(make_repo, {"package.json": '{"name": "x"}\n', "k.js": legacy}, name="b")
    assert [(r["path"], r["framework"]) for r in s["facts"]["k.js"]["routes"]] == [
        ("/orders/{id}", "koa-router-legacy"), ("/any", "koa-router-legacy")]


def test_fastify(make_repo):
    src = ("import Fastify from 'fastify';\nconst fastify = Fastify();\n"
           "fastify.get('/orders/:id', getOrder);\n"
           "fastify.post('/orders', { schema: {} }, async (req) => ({}));\n"
           "fastify.route({\n  method: 'DELETE',\n  url: '/orders/:id',\n  handler: drop,\n});\n"
           "fastify.route({ url: '/both', method: ['GET', 'HEAD'], handler: async () => 1 });\n"
           "fastify.register(adminRoutes, { prefix: '/admin' });\n"
           "reply.headers.get('x');\n"
           "function getOrder() {}\nfunction drop() {}\nfunction adminRoutes() {}\n")
    s = build(make_repo, {"package.json": '{"name": "x"}\n', "f.ts": src})
    f = s["facts"]["f.ts"]
    # an inline handler: the file, not the function defined below the call
    assert [(r["method"], r["path"], r["handler"].split("#")[-1], r["framework"]) for r in f["routes"]] == [
        ("GET", "/orders/{id}", "getOrder/0", "fastify"),
        ("POST", "/orders", ".::_root_/f.ts", "fastify"),
        ("DELETE", "/orders/{id}", "drop/0", "fastify-route"),
        ("GET", "/both", ".::_root_/f.ts", "fastify-route"),
        ("HEAD", "/both", ".::_root_/f.ts", "fastify-route")]
    assert [(m["path"], m["target"]) for m in f["mounts"]] == [("/admin", "adminRoutes")]


# Tables

@pytest.mark.parametrize("lang", ["typescript", "javascript"])
def test_orm_tables(lang):
    st = stack.default()

    def find(src, imports, klass=(), method=()):
        return [(t["table"], t["pattern"]) for t in stack.find_tables(st, lang, src, imports, list(method),
                                                                      list(klass), "f")]

    entity = ("@Entity('orders')\nclass A {}\n@Entity({ schema: 's', name: 'items' })\nclass B {}\n"
              "@Entity()\n@Index(['x'])\nexport class LineItem {}\n@Entity(\"x\")\n")
    assert find(entity, ["typeorm"]) == [("orders", "typeorm-entity"), ("x", "typeorm-entity"),
                                         ("items", "typeorm-entity-name"), ("LineItem", "typeorm-entity-class")]
    assert find(entity, ["@mikro-orm/core"]) == []
    prisma = ("const a = await prisma.order.findMany();\nawait this.prisma.lineItem.create({ data });\n"
              "await prisma.$transaction([]);\nprisma.helper.thing;\n")
    assert find(prisma, ["@prisma/client"]) == [("order", "prisma"), ("lineItem", "prisma")]
    assert find(prisma, ["./prisma.service"]) == []
    # with `tableName` in the define call's options the model name is not a table
    seq = ("const Order = sequelize.define('Order', {\n  id: DataTypes.INTEGER,\n  total: DataTypes.DECIMAL(10, 2),\n"
           "}, { tableName: 'orders' });\n"
           "class Item extends Model {}\nItem.init({}, { sequelize, tableName: 'items' });\n"
           "const Line = sequelize.define('Line', { qty: DataTypes.INTEGER(4) });\n")
    assert find(seq, ["sequelize"]) == [("Line", "sequelize-define"), ("orders", "sequelize-table-name"),
                                        ("items", "sequelize-table-name")]
    assert find(seq, ["sequelize-typescript"]) == [("orders", "sequelize-typescript-table-name"),
                                                   ("items", "sequelize-typescript-table-name")]
    assert find(seq, ["knex"]) == []
    # a later call's tableName does not suppress an earlier define without one
    two = "const A = sequelize.define('A', {});\nconst B = sequelize.define('B', {}, { tableName: 'bs' });\n"
    assert find(two, ["sequelize"]) == [("A", "sequelize-define"), ("bs", "sequelize-table-name")]


def test_typeorm_class_span_gives_defined(make_repo):
    s = build(make_repo, {"package.json": '{"name": "x"}\n',
                          "e.ts": "import { Entity } from 'typeorm';\n\n@Entity()\nexport class Order {\n  id: number;\n}\n"})
    assert tables(s, "e.ts") == [("Order", 3, ".::e.Order", "defined", "typeorm-entity-class")]


# Imports

@pytest.mark.parametrize("lang", ["typescript", "javascript"])
def test_js_import_kinds(lang):
    st = stack.default()
    for target, kind in (("pg", "sql-db"), ("mysql2/promise", "sql-db"), ("@prisma/client", "sql-db"),
                         ("typeorm", "sql-db"), ("sequelize", "sql-db"), ("knex", "sql-db"),
                         ("drizzle-orm/pg-core", "sql-db"), ("mongodb", "doc-db"), ("mongoose", "doc-db"),
                         ("kafkajs", "event"), ("amqplib", "event"), ("bullmq", "event"), ("ioredis", "cache"),
                         ("redis", "cache"), ("axios", "http-out"), ("node-fetch", "http-out"), ("got", "http-out"),
                         ("undici", "http-out"), ("express", "http-in"), ("koa", "http-in"), ("fastify", "http-in"),
                         ("@nestjs/core", "http-in"), ("@aws-sdk/client-s3", "cloud-sdk"),
                         ("@google-cloud/storage", "cloud-sdk"), ("@google-cloud/pubsub", "event"),
                         ("@grpc/grpc-js", "grpc"), ("@nestjs/typeorm", "sql-db"), ("@nestjs/axios", "http-out")):
        assert [h["kind"] for h in stack.sink_kinds(st, lang, target)] == [kind], (lang, target)
    for target in ("@nestjs/common", "@nestjs/config", "@nestjs/swagger", "node:fs", "path"):
        assert stack.covered(st, lang, target) and stack.sink_kinds(st, lang, target) == [], target
    # middleware packages are libraries the agent judges
    for target in ("cors", "helmet", "@fastify/cors", "koa-bodyparser", "pgx", "express-validator"):
        assert not stack.covered(st, lang, target), target


def test_js_and_ts_packs_carry_the_same_entries():
    st = stack.default()
    assert st.imports["typescript"] == [(p, k, s) for p, k, s in st.imports["javascript"]]
    assert st.ignore["typescript"] == st.ignore["javascript"]

    def shape(lang, items):
        return [(p.name, p.when, getattr(p, "regex", None) and p.regex.pattern) for p in items if p.lang == lang]

    assert shape("typescript", st.patterns) == shape("javascript", st.patterns)
    assert shape("typescript", st.tables) == shape("javascript", st.tables)


@pytest.mark.parametrize("lang", ["typescript", "javascript"])
def test_every_js_pack_regex_entry_has_when(lang):
    """A pack regex without `when` would fire on any file of the language."""
    st = stack.default()
    for p in (*st.patterns, *st.tables):
        if p.lang == lang and p.source == "pack":
            assert p.when, p.name


def test_nest_library_module_is_not_a_server(make_repo):
    """A Nest library module of services (imports @nestjs/common only) carries no http-in sink and no server line."""
    files = {"package.json": '{"name": "m", "private": true, "workspaces": ["libs/*"]}\n',
             "libs/core/package.json": '{"name": "@m/core"}\n',
             "libs/core/src/clock.service.ts": "import { Injectable } from '@nestjs/common';\n\n"
                                              "@Injectable()\nexport class ClockService {\n  now() { return 1; }\n}\n"}
    s = build(make_repo, files)
    assert sinks(s, "libs/core/src/clock.service.ts") == []
    assert s["stack"]["servers_without_routes"] == [] and s["stack"]["unrecognised"] == []
    assert "Server libraries without routes" not in structure.summary_md(s)
