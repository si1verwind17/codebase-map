"""HTTP client wrappers: a function passing its own parameter to an HTTP client is a wrapper, and a call to it with a
path literal is a request (format.md § http clients), so a frontend's calls through its own API helper are found."""
from conftest import with_stack


from vizcode.scan import structure


def clients(s, f):
    return [(c["method"], c["path"], c["in"].rsplit("::", 1)[-1]) for c in s["facts"][f].get("clients", [])
            if c.get("framework") != "tapir-client"]


def test_calls_through_a_layered_wrapper_object_are_requests(make_repo):
    files = {
        "package.json": '{"name": "web"}\n',
        "src/http.ts": "import axios from 'axios'\n\nexport const http = {\n"
                       "  get(url: string) { return this.request('get', url) },\n"
                       "  post(url: string, data: unknown) { return this.request('post', url, data) },\n"
                       "  request(method: string, url: string, data?: unknown) {\n"
                       "    return axios.request({ method, url: `/api/${url}`, data })\n  },\n}\n",
        "src/albums.ts": "import { http } from './http'\n\nconst cache = new Map<string, number>()\n\n"
                         "export const albumService = {\n"
                         "  fetch: (id: string) => http.get(`albums/${id}`),\n"
                         "  create: (name: string) => http.post('albums', { name }),\n"
                         "  cached: (k: string) => cache.get(k),\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "src/albums.ts") == [("GET", "/albums/{id}", "src/albums.ts#fetch/1"),
                                           ("POST", "/albums", "src/albums.ts#create/1")]
    assert clients(s, "src/http.ts") == []   # the wrapper's own calls are no requests


def test_a_free_function_wrapper_taking_an_options_object(make_repo):
    files = {
        "package.json": '{"name": "ui"}\n',
        "src/api.ts": "export async function apiFetch({ url, method }: { url: string; method?: string }) {\n"
                      "  return fetch(url, { method })\n}\n",
        "src/user.ts": "import { apiFetch } from './api'\n\nexport function login() {\n"
                       "  return apiFetch({\n    url: '/user/login',\n    method: 'POST',\n  })\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "src/user.ts") == [("POST", "/user/login", "src/user.ts#login/0")]


def test_a_direct_client_call_with_a_path(make_repo):
    files = {
        "build.gradle.kts": "\n",
        "src/main/kotlin/app/Api.kt": "package app\n\nimport io.ktor.client.HttpClient\nimport io.ktor.client.request.get\n\n"
                                      "class Api(private val client: HttpClient) {\n"
                                      "    suspend fun sessions() = client.get(\"sessions\")\n"
                                      "    suspend fun votes(year: Int) = client.get(\"$year/votes\")\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "src/main/kotlin/app/Api.kt") == [("GET", "/sessions", "app.Api#sessions/0"),
                                                         ("GET", "/{year}/votes", "app.Api#votes/1")]


def test_an_inline_route_handler_is_a_node_of_its_own(make_repo):
    """`r.Get("/x", func(w, r) {..})` and Ktor's `get("/x") { .. }` inside the function that registers them: each
    route's lambda is its own handler node, its calls its own, so traces do not mix the routes."""
    files = {
        "go.mod": "module example.com/app\n",
        "rest.go": "package rest\n\nimport \"github.com/go-chi/chi/v5\"\n\nfunc routes(r chi.Router) {\n"
                   "\tr.Get(\"/ping\", func(w http.ResponseWriter, req *http.Request) {\n\t\tpong(w)\n\t})\n"
                   "\tr.Post(\"/save\", func(w http.ResponseWriter, req *http.Request) {\n\t\tstore(req)\n\t})\n}\n\n"
                   "func pong(w http.ResponseWriter) {}\n\nfunc store(r *http.Request) {}\n"}
    s = structure.build(make_repo(files))
    rs = s["facts"]["rest.go"]["routes"]
    handlers = {r["path"]: r["handler"] for r in rs}
    assert handlers["/ping"] != handlers["/save"] and not handlers["/ping"].endswith("#routes/1")
    names = {n["id"]: n["name"] for n in s["nodes"]}
    assert (names[handlers["/ping"]], names[handlers["/save"]]) == ("get_ping", "post_save")
    calls = {c["callee"]: c["in"] for c in s["facts"]["rest.go"]["calls"]}
    assert calls["pong"] == handlers["/ping"] and calls["store"] == handlers["/save"]


def test_sql_in_mapper_xml_and_tables_defined_in_sql_files(make_repo):
    """A MyBatis mapper's statements are SQL facts of the interface method their id names; `CREATE TABLE` in a
    `.sql` file is listed, so tables kept out of the code are never silently missing."""
    files = {"pom.xml": "<project/>\n",
             "src/main/java/a/mapper/UserMapper.java":
                 "package a.mapper;\n\nimport org.apache.ibatis.annotations.Mapper;\n\n@Mapper\n"
                 "public interface UserMapper {\n    User selectById(Long id);\n    int insert(User u);\n}\n",
             "src/main/resources/a/mapper/UserMapper.xml":
                 '<?xml version="1.0"?>\n<mapper namespace="a.mapper.UserMapper">\n'
                 '  <select id="selectById" resultType="a.User">\n    select id, name from ums_user where id = #{id}\n'
                 '  </select>\n  <insert id="insert">\n    insert into ums_user (name) values (#{name})\n  </insert>\n'
                 '</mapper>\n',
             "db/migrations/V1__init.sql": "-- schema\nCREATE TABLE IF NOT EXISTS sessions (\n  id INT\n);\n"
                                           "create table \"votes\" (id int);\n"}
    s = structure.build(make_repo(files))
    sql = s["facts"]["src/main/java/a/mapper/UserMapper.java"]["sql"]
    assert [(q["in"].rsplit("#", 1)[-1], q["reads"], q["writes"], q["source"]) for q in sql] == [
        ("selectById/1", ["ums_user"], [], "src/main/resources/a/mapper/UserMapper.xml:3"),
        ("insert/1", [], ["ums_user"], "src/main/resources/a/mapper/UserMapper.xml:6")]
    assert s["sql_files"] == [{"file": "db/migrations/V1__init.sql", "line": 2, "table": "sessions"},
                              {"file": "db/migrations/V1__init.sql", "line": 5, "table": "votes"}]
    md = structure.summary_md(s)
    assert "## Tables defined in SQL, schema and migration files — 2" in md and "- sessions (db/migrations/V1__init.sql:2)" in md


def test_look_alikes_in_a_client_file_are_no_requests(make_repo):
    """In files that import an HTTP client: a session, a header map, a cache client, a router registering
    routes, a `path:` field of a body, a non-HTTP import named `get`, a Map named like a wrapper file."""
    files = {
        "app/__init__.py": "",
        "app/views.py": "import requests\nfrom flask import session\n\n\ndef me(r):\n"
                        "    uid = session.get('user_id')\n    acc = http_headers.get('Accept')\n"
                        "    tok = redis_client.get('token:1')\n    return requests.get('/profile')\n",
        "package.json": '{"name": "web"}\n',
        "src/http.ts": "import axios from 'axios'\nexport const http = {\n  get(url: string) { return axios.get(url) },\n}\n",
        "src/lib.ts": "export function get(key: string) { return key }\n",
        "src/server.ts": "import axios from 'axios'\nimport { get } from './lib'\nimport express from 'express'\n\n"
                         "export function mount(apiRouter: express.Router) {\n  apiRouter.post('/save', save)\n"
                         "  axios.post('/upload', { path: 'avatar.png' })\n"
                         "  axios.get('/a').then(() => axios.get('/b'))\n  get('/v')\n  const http = new Map()\n"
                         "  http.get('token')\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "app/views.py") == [("GET", "/profile", "app.views#me/1")]
    assert clients(s, "src/server.ts") == [("POST", "/upload", "src/server.ts#mount/1"),
                                           ("GET", "/a", "src/server.ts#mount/1"), ("GET", "/b", "src/server.ts#mount/1")]


def test_a_wrapper_in_an_index_file_is_named_by_its_folder(make_repo):
    files = {"package.json": '{"name": "web"}\n',
             "src/http/index.ts": "import axios from 'axios'\nexport function get(url: string) { return axios.get(url) }\n",
             "src/users.ts": "import * as http from './http'\nexport function list() { return http.get('/users') }\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "src/users.ts") == [("GET", "/users", "src/users.ts#list/0")]


def test_mapper_cdata_quoted_schemas_and_commented_creates(make_repo):
    files = {"pom.xml": "<project/>\n",
             "src/main/java/a/M.java": "package a;\n\nimport org.apache.ibatis.annotations.Mapper;\n\n"
                                       "public interface M {\n    java.util.List<Long> recent();\n}\n",
             "src/main/resources/M.xml": '<mapper namespace="a.M">\n  <select id="recent">\n'
                                         "    <![CDATA[ SELECT id FROM users WHERE age < 30 ]]>\n  </select>\n</mapper>\n",
             "db/schema.sql": 'CREATE TABLE "public"."accounts" (id int);\n/* CREATE TABLE ghost (id int); */\n'
                              "CREATE GLOBAL TEMPORARY TABLE scratch (id int);\n"}
    s = structure.build(make_repo(files))
    assert [q["reads"] for q in s["facts"]["src/main/java/a/M.java"]["sql"]] == [["users"]]
    assert [d["table"] for d in s["sql_files"]] == ["public.accounts", "scratch"]


def test_an_inline_handler_is_the_lambda_on_the_route_line_only(make_repo):
    files = {"go.mod": "module example.com/app\n",
             "rest.go": "package rest\n\nimport \"github.com/go-chi/chi/v5\"\n\nfunc routes(r chi.Router) {\n"
                        "\tr.Get(\"/\", func(w http.ResponseWriter, req *http.Request) {})\n"
                        "\tr.Get(\"/{id}\", func(w http.ResponseWriter, req *http.Request) {})\n"
                        "\tr.Get(\"/x\", named)\n\tgo func() { warm() }()\n}\n"}
    s = structure.build(make_repo(files))
    names = {n["id"]: n["name"] for n in s["nodes"]}
    got = {r["path"]: names.get(r["handler"], r["handler"]) for r in s["facts"]["rest.go"]["routes"]}
    assert got["/"] == "get" and got["/{id}"] == "get_id" and got["/x"] != "get_x"


def test_a_wrapper_from_another_python_module_or_the_same_java_package(make_repo):
    files = {"a/__init__.py": "", "a/api.py": "import requests\n\n\ndef call(url):\n    return requests.get(url)\n",
             "a/one.py": "from a.api import call\n\n\ndef run():\n    return call('/w')\n",
             "a/two.py": "from a import api\n\n\ndef run():\n    return api.call('/v')\n",
             "pom.xml": "<project/>\n",
             "src/main/java/p/Http.java": "package p;\n\nimport java.net.http.HttpClient;\n\npublic class Http {\n"
                                          "    HttpClient client;\n    public String get(String url) { return client.send(url); }\n}\n",
             "src/main/java/p/Use.java": "package p;\n\npublic class Use {\n    Http http;\n"
                                         "    void go() { http.get(\"/j\"); }\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "a/one.py") == [("GET", "/w", "a.one#run/0")]
    assert clients(s, "a/two.py") == [("GET", "/v", "a.two#run/0")]
    assert clients(s, "src/main/java/p/Use.java") == [("GET", "/j", "p.Use#go/0")]


def test_a_method_passed_first_is_the_method_not_the_path(make_repo):
    files = {"a/__init__.py": "", "a/api.py": "import requests\n\n\ndef call(method, url):\n"
                                                "    return requests.request(method, url)\n",
             "a/use.py": "from a.api import call\n\n\ndef run():\n    return call('POST', '/jobs')\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "a/use.py") == [("POST", "/jobs", "a.use#run/0")]


def test_a_route_handler_beside_a_plain_module_import(make_repo):
    """`import x` records no names: finding where a pattern's handler name comes from must not trip over it."""
    files = {"app/__init__.py": "", "app/views.py": "def ping():\n    return 'ok'\n",
             "app/urls.py": "import os\nfrom app.views import ping\n\nurlpatterns = [path('ping/', ping)]\n"}
    repo = make_repo(files)
    with_stack(repo, "python:\n  routes:\n    - name: django-path\n      path: literal\n      method: ANY\n"
                     "      regex: '\\bpath\\(\\s*[\"''](?P<path>[^\"'']*)[\"'']\\s*,\\s*(?P<handler>\\w+)'\n")
    s = structure.build(repo, "docs/viz-code")
    assert [r["handler"] for r in s["facts"]["app/urls.py"]["routes"]] == ["app::app.views#ping/0"]


def test_request_descriptors_and_the_apps_own_client_class(make_repo):
    """`request(cfg, {method, url})` from a generated client, a query definition returning `{method, url}`, and
    the app's own `XClient.get({endpoint})` whose library this file does not import; a server's route object
    (`{method, path, handler}`) and an axios call already read are not counted (again)."""
    files = {"package.json": '{"name": "ui"}\n',
             "src/gen/services.ts": "import { request } from './core/request'\n\nexport class AssetService {\n"
                                    "  static getAsset(id: string) {\n    return request(OpenAPI, {\n      method: 'GET',\n"
                                    "      url: '/api/v2/assets/{asset_id}',\n      path: { asset_id: id },\n    })\n  }\n}\n",
             "src/api/user.ts": "export const userApi = api.injectEndpoints({\n  endpoints: (builder) => ({\n"
                                "    getUser: builder.query({\n      query: (id) => ({\n        method: 'GET',\n"
                                "        url: `/api/user/${id}`,\n      }),\n    }),\n  }),\n})\n",
             "src/charts.ts": "import { ApiClient } from '@acme/ui-core'\n\n"
                              "export function load(id: number) {\n  return ApiClient.get({ endpoint: `/api/v1/chart/${id}` })\n}\n"
                              "export function local(k: string) {\n  return cacheClient.get(k)\n}\n",
             "src/server.ts": "import Hapi from '@hapi/hapi'\n\nexport function start(server) {\n"
                              "  server.route({ method: 'GET', path: '/items', handler: list })\n}\n",
             "src/up.ts": "import axios from 'axios'\n\nexport function up() {\n  return axios({\n    method: 'post',\n"
                          "    url: '/upload',\n  })\n}\n"}
    s = structure.build(make_repo(files))
    assert [(c["method"], c["path"]) for c in s["facts"]["src/gen/services.ts"]["clients"]] == [
        ("GET", "/api/v2/assets/{asset_id}")]
    assert [(c["method"], c["path"]) for c in s["facts"]["src/api/user.ts"]["clients"]] == [("GET", "/api/user/{id}")]
    assert clients(s, "src/charts.ts") == [("GET", "/api/v1/chart/{id}", "src/charts.ts#load/1")]
    assert s["facts"]["src/server.ts"].get("clients", []) == []
    assert [(c["method"], c["path"]) for c in s["facts"]["src/up.ts"]["clients"]] == [("POST", "/upload")]


def test_route_tables_contracts_and_key_stores_are_no_requests(make_repo):
    """Objects with a method and a path that a server or a contract declares (an array entry, a property value), and
    a key store's client called with a `/`-rooted key, are no outbound requests."""
    files = {"package.json": '{"name": "svc"}\n',
             "src/serverless.ts": "export const fn = { handler: 'h.main', events: [{ http: { method: 'post', path: '/hello' } }] }\n",
             "src/routes.ts": "export const routes = [\n  { method: 'get', path: '/users', action: list },\n"
                              "  { method: 'post', url: '/users', fn: create },\n]\n",
             "src/contract.ts": "export const c = c.router({\n  getPost: { method: 'GET', path: '/posts/:id', responses: {} },\n})\n",
             "src/zk.ts": "export function drop() {\n  return zkClient.delete('/brokers/ids/1')\n}\n",
             "app/__init__.py": "", "app/locks.py": "def release(self):\n    self.zk_client.delete('/locks/job')\n"}
    s = structure.build(make_repo(files))
    assert {f: ff["clients"] for f, ff in s["facts"].items() if ff.get("clients")} == {}


def test_a_literal_inside_the_address_expression_is_no_path(make_repo):
    """A route-name helper, a lookup, a choice and a header read name no path; a literal joined onto a base does."""
    files = {"package.json": '{"name": "ui"}\n',
             "src/a.ts": "import axios from 'axios'\n\nexport function go(o: any, f: boolean) {\n"
                         "  axios.get(route('close_beta'))\n  axios.post(o.get('url'))\n"
                         "  axios.put(f ? 'always_invoice' : 'none')\n  axios.get(base + '/users')\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "src/a.ts") == [("GET", "/users", "src/a.ts#go/2")]


def test_tables_created_by_orm_schemas_and_migrations(make_repo):
    """Rails schema.rb, Laravel, Knex/Sequelize, EF Core, Liquibase and Django migrations list the tables they
    create, once each; the same call outside a schema or migration path is not read."""
    files = {"Gemfile": "gem 'rails'\n",
             "db/schema.rb": 'ActiveRecord::Schema.define do\n  create_table "accounts", id: :uuid do |t|\n  end\nend\n',
             "composer.json": "{}\n",
             "database/migrations/2014_create_users.php": "<?php\nSchema::create('contacts', function ($t) {});\n",
             "package.json": '{"name": "s"}\n',
             "server/migrations/2026-create.js": "module.exports = { up: (q) => q.createTable('access_requests', {}) }\n",
             "server/util.js": "export const f = (q) => q.createTable('not_a_migration', {})\n",
             "Db/Db.csproj": "<Project/>\n",
             "Db/Migrations/2020_AddUser.cs": "class AddUser { void Up(M b) { b.CreateTable(\n    name: \"Users\",\n"
                                              "    columns: t => null); } }\n",
             "src/main/resources/config/liquibase/changelog/0_initial.xml":
                 '<databaseChangeLog>\n  <createTable tableName="jhi_user">\n  </createTable>\n</databaseChangeLog>\n',
             "shop/__init__.py": "", "shop/orders/__init__.py": "", "shop/orders/migrations/__init__.py": "",
             "shop/orders/migrations/0001_initial.py":
                 "from django.db import migrations\n\nclass Migration(migrations.Migration):\n    operations = [\n"
                 "        migrations.CreateModel(name='Order', fields=[]),\n"
                 "        migrations.CreateModel(name='Line', fields=[], options={'db_table': 'order_lines'}),\n    ]\n"}
    s = structure.build(make_repo(files))
    assert sorted(d["table"] for d in s["sql_files"]) == ["Users", "access_requests", "accounts", "contacts", "jhi_user",
                                                         "order_lines", "orders_order"]


def test_orm_calls_on_entities_are_table_access(make_repo):
    """A call on an entity class whose table is known reads or writes it, by the verb: a SQLAlchemy model's own
    table, a Django model its migration creates, a Rails model by the naming default; `cls.query` inside the entity
    counts for itself; a name two entities share names no table."""
    files = {"app/__init__.py": "",
             "app/models.py": "from sqlalchemy.orm import declarative_base\n\nBase = declarative_base()\n\n\n"
                              "class Order(Base):\n    __tablename__ = 'orders'\n\n    @classmethod\n"
                              "    def recent(cls):\n        return cls.query.filter_by(done=False).all()\n",
             "app/views.py": "from app.models import Order\n\n\ndef show(i):\n    return Order.query.get(i)\n\n\n"
                             "def drop(i):\n    Order.query.filter_by(id=i).delete()\n",
             "shop/__init__.py": "", "shop/orders/__init__.py": "", "shop/orders/migrations/__init__.py": "",
             "shop/orders/migrations/0001_initial.py": "operations = [migrations.CreateModel(name='Line', fields=[])]\n",
             "shop/orders/models.py": "from django.db import models\n\n\nclass Line(models.Model):\n    pass\n",
             "shop/orders/services.py": "from shop.orders.models import Line\n\n\ndef add(o):\n"
                                        "    return Line.objects.create(order=o)\n",
             "Gemfile": "gem 'rails'\n", "db/schema.rb": 'create_table "categories" do |t|\nend\n',
             "app/models/category.rb": "class Category < ApplicationRecord\nend\n",
             "app/services/sorter.rb": "class Sorter\n  def run\n    Category.where(active: true).order(:name)\n"
                                       "    Session.get('x')\n  end\nend\n",
             "lib/session.rb": "class Session\n  def self.get(k)\n  end\nend\n",
             "db/migrate/1_sessions.rb": 'create_table "sessions" do |t|\nend\n'}
    s = structure.build(make_repo(files))
    acc = sorted((t["table"], t["op"], t["in"].rsplit("#", 1)[-1]) for ff in s["facts"].values()
                 for t in ff.get("tables", []) if t.get("pattern") == "orm-call")
    assert acc == [("categories", "read", "run/0"), ("orders", "read", "recent/0"), ("orders", "read", "show/1"),
                   ("orders", "write", "drop/1"), ("orders_line", "write", "add/1")]


def test_an_inline_handler_at_the_file_top_is_its_own_node(make_repo):
    """`router.post("docs.info", auth(), async (ctx) => {..})` at a file's top, arguments over several lines: the
    lambda is a method of the file named after the route, and the calls inside it are its."""
    files = {"package.json": '{"name": "s", "dependencies": {"@koa/router": "12"}}\n',
             "src/r.ts": "import Router from '@koa/router'\nconst router = new Router()\n"
                         "router.post(\n  'docs.info',\n  auth(),\n  async (ctx) => {\n    ctx.body = await load(ctx)\n  },\n)\n"
                         "router.get('docs.list', async (ctx) => { ctx.body = await list() })\n"
                         "function load(c) { return c }\nfunction list() { return [] }\nfunction auth() { return 1 }\n"
                         "export default router\n"}
    s = structure.build(make_repo(files))
    rs = {r["path"]: r["handler"] for r in s["facts"]["src/r.ts"]["routes"]}
    assert rs == {"/docs.info": ".::src/r.ts#post_docs_info/0", "/docs.list": ".::src/r.ts#get_docs_list/0"}
    ins = {c["callee"]: c["in"] for c in s["facts"]["src/r.ts"]["calls"]}
    assert ins["load"] == rs["/docs.info"] and ins["list"] == rs["/docs.list"] and ins["auth"] is None


def test_a_file_level_lambda_belongs_only_to_the_route_call_holding_it(make_repo):
    """An error middleware after a route that names its handler is no handler of that route; a Rails
    `resources .. do` block makes no handler for the resource's routes."""
    files = {"package.json": '{"name": "s", "dependencies": {"express": "4"}}\n',
             "src/app.js": "const express = require('express')\nconst app = express()\n"
                           "app.get('/metrics', promBundle.metricsMiddleware)\n"
                           "app.use((err, req, res, next) => {\n  log(err)\n})\n",
             "Gemfile": "gem 'rails'\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  resources :users do\n    get :export\n  end\nend\n"}
    s = structure.build(make_repo(files))
    assert [r["handler"] for r in s["facts"]["src/app.js"]["routes"]] == [".::src/app.js"]
    assert not any("#get_users" in r["handler"] for r in s["facts"]["config/routes.rb"]["routes"])


def test_concatenated_and_built_addresses(make_repo):
    files = {"package.json": '{"name": "ui"}\n',
             "src/a.ts": "import axios from 'axios'\n\nexport function go(id: string) {\n"
                         "  axios.get('/api/users/' + id)\n  axios.delete(BASE + '/api/b/' + String(id))\n}\n",
             "app/__init__.py": "",
             "app/c.py": "import requests\nfrom urllib.parse import urljoin\n\n\ndef c(i):\n"
                         "    requests.get(urljoin(BASE, '/api/c'))\n    requests.post(BASE + '/api/d/' + str(i) + '/x')\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "src/a.ts")] == [("GET", "/api/users/{id}"), ("DELETE", "/api/b/{id}")]
    assert [(m, p) for m, p, _ in clients(s, "app/c.py")] == [("GET", "/api/c"), ("POST", "/api/d/{i}/x")]


def test_formatted_held_and_folded_addresses_and_more_client_calls(make_repo):
    """A format call, a local variable, a file's path constant, a placeholder host, C#'s typed HttpClient with
    implicit usings, Go net/http, a WebClient `.uri` chain and a Locust user all give their request."""
    files = {"app/__init__.py": "",
             "app/pay.py": "import requests\n\n\ndef pay(host, i):\n    requests.get('http://{}:8080/api/pay/{}'.format(host, i))\n"
                           "    url = BASE + '/cart/' + str(i)\n    requests.delete(url)\n",
             "app/load.py": "from locust import HttpUser\n\n\nclass U(HttpUser):\n    def view(self):\n"
                            "        self.client.get('/api/cart')\n",
             "package.json": '{"name": "ui"}\n',
             "src/api.ts": "import axios from 'axios'\nconst basePath = '/api'\n\nexport function add(id: string) {\n"
                           "  return axios.post(`${basePath}/cart/${id}`)\n}\n",
             "Web/Web.csproj": "<Project/>\n",
             "Web/Catalog.cs": "namespace Web;\npublic class Catalog(HttpClient httpClient)\n{\n"
                               "    private readonly string baseUrl = \"api/catalog/\";\n"
                               "    public Task<Item> Get(int id)\n    {\n        var uri = $\"{baseUrl}items/{id}?x=1\";\n"
                               "        return httpClient.GetFromJsonAsync<Item>(uri);\n    }\n}\n",
             "go.mod": "module shop\n",
             "front/cart.go": "package front\n\nimport (\n\t\"fmt\"\n\t\"net/http\"\n)\n\n"
                              "func View(base string, id int) {\n\turl := fmt.Sprintf(\"%s/cart/%d\", base, id)\n\thttp.Get(url)\n}\n",
             "pom.xml": "<project/>\n",
             "src/main/java/a/Vets.java": "package a;\nimport org.springframework.web.reactive.function.client.WebClient;\n"
                                          "public class Vets {\n    private WebClient webClient;\n    public Object all() {\n"
                                          "        return webClient.get()\n            .uri(\"/vets/{id}\", 1)\n"
                                          "            .retrieve();\n    }\n}\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "app/pay.py")] == [("GET", "/api/pay/{v}"), ("DELETE", "/cart/{i}")]
    assert [(m, p) for m, p, _ in clients(s, "app/load.py")] == [("GET", "/api/cart")]
    assert [(m, p) for m, p, _ in clients(s, "src/api.ts")] == [("POST", "/api/cart/{id}")]
    assert [(m, p) for m, p, _ in clients(s, "Web/Catalog.cs")] == [("GET", "/api/catalog/items/{id}")]
    assert [(m, p) for m, p, _ in clients(s, "front/cart.go")] == [("GET", "/cart/{v}")]
    assert [(m, p) for m, p, _ in clients(s, "src/main/java/a/Vets.java")] == [("GET", "/vets/{id}")]


def test_a_client_factory_and_a_method_first_call_over_lines(make_repo):
    """`boto3.client("s3")` makes a client, it sends nothing; `request(\\n "POST",\\n "/jobs")` is a POST."""
    files = {"app/__init__.py": "",
             "app/s3.py": "import boto3\n\n\ndef put(k):\n    boto3.client('s3').put_object(Key=k)\n",
             "app/api.py": "import requests\n\n\ndef call(method, url):\n    return requests.request(method, url)\n",
             "app/use.py": "from app.api import call\n\n\ndef run():\n    return call(\n        'POST',\n        '/jobs',\n    )\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "app/s3.py") == []
    assert clients(s, "app/use.py") == [("POST", "/jobs", "app.use#run/0")]


def test_orm_access_through_typed_repositories_and_ef_dbsets(make_repo):
    """A field typed with an entity (`Repository<User>`) reaches its table; an EF context's `DbSet<T> Users`
    names a table that `_context.Users.Where(..)` reads; the context itself is no entity."""
    files = {"package.json": '{"name": "a", "dependencies": {"typeorm": "0.3"}}\n',
             "src/user.entity.ts": "import { Entity } from 'typeorm'\n@Entity('users')\nexport class User {}\n",
             "src/users.service.ts": "import { Repository } from 'typeorm'\nimport { User } from './user.entity'\n"
                                     "export class UsersService {\n  constructor(private readonly repo: Repository<User>) {}\n"
                                     "  find(id: number) { return this.repo.findOneBy({ id }) }\n"
                                     "  add(u: User) { return this.repo.save(u) }\n}\n",
             "Api/Api.csproj": "<Project/>\n",
             "Api/AppDb.cs": "using Microsoft.EntityFrameworkCore;\nnamespace Api;\npublic class AppDb : DbContext\n{\n"
                             "    public DbSet<Order> Orders { get; set; }\n    public DbSet<Line> Lines { get; set; }\n}\n",
             "Api/OrdersRepo.cs": "using Microsoft.EntityFrameworkCore;\nnamespace Api;\npublic class OrdersRepo\n{\n"
                                  "    private readonly AppDb _context;\n"
                                  "    public object Open() { return _context.Orders.Where(o => o.Open).ToListAsync(); }\n"
                                  "    public void Add(Line l) { _context.Lines.Add(l); }\n}\n"}
    s = structure.build(make_repo(files))
    acc = sorted((t["table"], t["op"], t["in"].rsplit("#", 1)[-1]) for ff in s["facts"].values()
                 for t in ff.get("tables", []) if t.get("pattern") == "orm-call")
    assert acc == [("Lines", "write", "Add/1"), ("Orders", "read", "Open/0"),
                   ("users", "read", "find/1"), ("users", "write", "add/1")]


def test_orm_access_needs_the_entity_or_its_repository_and_a_context_for_a_dbset(make_repo):
    """A list of entities, a same-named interface elsewhere, a relation attribute in between, or a DbSet's name on
    another object reads no table."""
    files = {"package.json": '{"name": "a", "dependencies": {"typeorm": "0.3"}}\n',
             "src/user.ts": "import { Entity } from 'typeorm'\n@Entity()\nexport class User {}\n",
             "src/svc.ts": "import { User } from './user'\nexport function pick(users: User[]) { return users.find(u => u) }\n"
                           "export function all(users: Array<User>) { return users.filter(u => u) }\n",
             "web/ui.ts": "interface User { name: string }\nexport function show(users: User) { return users.find(1) }\n",
             "Api/Api.csproj": "<Project/>\n",
             "Api/AppDb.cs": "using Microsoft.EntityFrameworkCore;\nnamespace Api;\npublic class AppDb : DbContext\n{\n"
                             "    public DbSet<Item> Items { get; set; }\n}\n",
             "Api/Cart.cs": "namespace Api;\npublic class Cart\n{\n    public void Add(Response response, string x)\n    {\n"
                            "        response.Items.Add(x);\n        this.Items.Add(x);\n    }\n}\n"}
    s = structure.build(make_repo(files))
    assert [t for ff in s["facts"].values() for t in ff.get("tables", []) if t.get("pattern") == "orm-call"] == []


def test_orm_access_through_a_django_queryset_and_a_nested_ef_context(make_repo):
    files = {"requirements.txt": "django\n", "app/__init__.py": "", "app/migrations/__init__.py": "",
             "app/migrations/0001_initial.py": "from django.db import migrations\n\n\nclass Migration(migrations.Migration):\n"
                                               "    operations = [migrations.CreateModel(name='Ping', fields=[], "
                                               "options={'db_table': 'pings'})]\n",
             "app/models.py": "from django.db import models\n\n\nclass Ping(models.Model):\n    class Meta:\n"
                              "        db_table = 'pings'\n",
             "app/admin.py": "from django.db.models import QuerySet\nfrom app.models import Ping\n\n\n"
                             "def queryset(request, qs: QuerySet[Ping]):\n    return qs.filter(kind=1)\n",
             "Api/Api.csproj": "<Project/>\n",
             "Api/AppDb.cs": "using Microsoft.EntityFrameworkCore;\nnamespace Api;\npublic class AppDb : DbContext\n{\n"
                             "    public DbSet<Item> Items { get; set; }\n}\n",
             "Api/Svc.cs": "namespace Api;\npublic class Svc\n{\n    public object A(IUnitOfWork unitOfWork)\n    {\n"
                           "        return unitOfWork.DataContext.Items.ToListAsync();\n    }\n"
                           "    public void B(HttpRequest request) { request.HttpContext.Items.Add(\"k\", 1); }\n"
                           "    private readonly HttpContext _httpContext;\n"
                           "    public void C() { _httpContext.Items.Add(\"k\", 1); }\n}\n"}
    s = structure.build(make_repo(files))
    acc = sorted((t["table"], t["op"], t["in"].rsplit("#", 1)[-1]) for ff in s["facts"].values()
                 for t in ff.get("tables", []) if t.get("pattern") == "orm-call")
    assert acc == [("Items", "read", "A/1"), ("pings", "read", "queryset/2")]


def test_a_spring_data_repository_reaches_its_entitys_table(make_repo):
    """`OrderRepository extends JpaRepository<Order, Long>`: its inherited and derived methods read and write the
    entity's table; an entity's own getter (`order.getName()`) reads none."""
    files = {"pom.xml": "<project/>\n",
             "src/main/java/a/Order.java": "package a;\nimport jakarta.persistence.*;\n@Entity\n@Table(name = \"orders\")\n"
                                           "public class Order {\n    public String getName() { return null; }\n}\n",
             "src/main/java/a/OrderRepository.java": "package a;\nimport org.springframework.data.jpa.repository.JpaRepository;\n"
                                                     "public interface OrderRepository extends JpaRepository<Order, Long> {\n"
                                                     "    Order findByName(String n);\n}\n",
             "src/main/java/a/Orders.java": "package a;\npublic class Orders {\n    private OrderRepository repo;\n"
                                            "    public Object one(long id) { return repo.findById(id); }\n"
                                            "    public Object named(String n) { return repo.findByName(n); }\n"
                                            "    public void put(Order o) { repo.saveAll(java.util.List.of(o)); }\n"
                                            "    public String label(Order o) { return o.getName(); }\n}\n"}
    s = structure.build(make_repo(files))
    acc = sorted((t["table"], t["op"], t["in"].rsplit("#", 1)[-1]) for ff in s["facts"].values()
                 for t in ff.get("tables", []) if t.get("pattern") == "orm-call")
    assert acc == [("orders", "read", "named/1"), ("orders", "read", "one/1"), ("orders", "write", "put/1")]


def test_built_addresses_stay_honest(make_repo):
    """Two verbs on one line are two requests; a path of placeholders only is none; a loop variable takes no
    other function's local; a wrapper named `getResponse` passing its caller's verb is no GET; Go `api.Get` on a
    store is no request."""
    files = {"app/__init__.py": "",
             "app/a.py": "import httpx\nimport asyncio\nimport requests\n\n\ndef both():\n"
                         "    return asyncio.gather(httpx.get('/items'), httpx.post('/items'))\n\n\n"
                         "def s3(bucket, key):\n    return requests.get(f'https://{bucket}.s3.amazonaws.com/{key}')\n\n\n"
                         "def a():\n    url = '/a/admin'\n    return url\n\n\ndef b(items):\n    for url in items:\n"
                         "        requests.get(url)\n",
             "package.json": '{"name": "ui"}\n',
             "src/api.ts": "export class Api {\n  getResponse(url: string, method: string) { return fetch(url, {method}) }\n"
                           "  save(id: string) { return this.getResponse(`/items/${id}`, 'POST') }\n}\n",
             "go.mod": "module shop\n",
             "svc/svc.go": "package svc\n\nimport \"net/http\"\n\ntype Svc struct{ api *Store }\n\n"
                           "func (s *Svc) Load(id string) { s.api.Get(\"users/\" + id); _ = http.StatusOK }\n"}
    s = structure.build(make_repo(files))
    assert sorted((m, p) for m, p, _ in clients(s, "app/a.py")) == [("GET", "/items"), ("POST", "/items")]
    assert [(m, p) for m, p, _ in clients(s, "src/api.ts")] == [("POST", "/items/{id}")]
    assert clients(s, "svc/svc.go") == []


def test_a_made_client_a_body_word_and_constants_of_a_class_or_a_method(make_repo):
    """Go `client := &http.Client{..}` sends; a verb word in a request body is no verb; a class constant resolves;
    a Java method's `final` local is no file constant."""
    files = {"go.mod": "module shop\n",
             "svc/a.go": "package svc\n\nimport \"net/http\"\n\nfunc Local() {\n\tclient := &http.Client{Timeout: 5}\n"
                         "\tclient.Get(\"/local\")\n}\n",
             "package.json": '{"name": "ui"}\n',
             "src/api.ts": "export class Api {\n  send(url: string, body: any) { return fetch(url, {method: 'POST', body}) }\n"
                           "  mark(id: string) { return this.send(`/items/${id}`, {\"status\": \"delete\"}) }\n}\n",
             "app/__init__.py": "",
             "app/c.py": "import requests\n\n\nclass Api:\n    BASE = '/api/v1/items'\n\n    def list(self):\n"
                         "        return requests.get(self.BASE)\n",
             "pom.xml": "<project/>\n",
             "src/main/java/a/W.java": "package a;\nimport org.springframework.web.client.RestTemplate;\npublic class W {\n"
                                       "    private RestTemplate rest;\n    void a() { final String base = \"/local/a\"; }\n"
                                       "    Object c() { return rest.getForObject(base + \"/x\", Object.class); }\n}\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "svc/a.go")] == [("GET", "/local")]
    assert [(m, p) for m, p, _ in clients(s, "src/api.ts")] == [("POST", "/items/{id}")]
    assert [(m, p) for m, p, _ in clients(s, "app/c.py")] == [("GET", "/api/v1/items")]
    assert [(m, p) for m, p, _ in clients(s, "src/main/java/a/W.java")] == [("GET", "/x")]


def test_a_made_client_binds_in_its_own_function_only(make_repo):
    files = {"go.mod": "module shop\n",
             "svc/a.go": "package svc\n\nimport \"net/http\"\n\nfunc A() {\n\tclient := &http.Client{}\n\tclient.Get(\"/a\")\n}\n\n"
                         "func B(client *cache.Cache) {\n\tclient.Get(\"user:1\")\n}\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "svc/a.go")] == [("GET", "/a")]


def test_a_client_bound_on_the_object_holds_in_the_classs_other_methods(make_repo):
    files = {"app/__init__.py": "",
             "app/c.py": "from rest import RestClient\n\n\nclass Api:\n    def __init__(self):\n"
                         "        self.api = RestClient('http://cart')\n\n    def view(self):\n"
                         "        return self.api.get('/cart')\n",
             "package.json": '{"name": "ui"}\n',
             "src/a.ts": "export class A {\n  constructor() {\n    this.http = new HttpClient()\n  }\n"
                         "  view() { return this.http.get('/cart') }\n}\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "app/c.py")] == [("GET", "/cart")]
    assert [(m, p) for m, p, _ in clients(s, "src/a.ts")] == [("GET", "/cart")]


def test_a_client_bound_on_the_object_is_its_classs_alone(make_repo):
    files = {"app/__init__.py": "",
             "app/c.py": "from rest import RestClient\n\n\nclass Api:\n    def __init__(self):\n"
                         "        self.store = RestClient('http://cart')\n\n    def view(self):\n"
                         "        return self.store.get('/cart')\n\n\nclass Repo:\n    def __init__(self, db):\n"
                         "        self.store = db\n\n    def load(self):\n        return self.store.get('/user/1')\n\n\n"
                         "def lookup(store):\n    return store.get('/k/v')\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "app/c.py")] == [("GET", "/cart")]


def test_a_client_bound_in_a_base_class_holds_in_its_subclass(make_repo):
    files = {"app/__init__.py": "",
             "app/c.py": "from rest import RestClient\n\n\nclass Base:\n    def __init__(self):\n"
                         "        self.api = RestClient('a')\n\n\nclass Cart(Base):\n    def view(self):\n"
                         "        return self.api.get('/cart')\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "app/c.py")] == [("GET", "/cart")]


def test_a_client_bound_in_a_base_class_of_another_file(make_repo):
    files = {"app/__init__.py": "",
             "app/base.py": "from rest import RestClient\n\n\nclass Base:\n    def __init__(self):\n"
                            "        self.api = RestClient('a')\n",
             "app/cart.py": "from app.base import Base\n\n\nclass Cart(Base):\n    def view(self):\n"
                            "        return self.api.get('/cart')\n",
             "app/store.py": "from app.base import Base\n\n\nclass Store(Base):\n    def __init__(self, db):\n"
                             "        self.api = db\n\n    def load(self):\n        return self.api.get('/user/1')\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "app/cart.py")] == [("GET", "/cart")]
    # a subclass binding the name to something else: its own value, no client
    assert clients(s, "app/store.py") == []


def test_a_subclass_binding_an_injected_client_keeps_the_base_client(make_repo):
    files = {"app/__init__.py": "",
             "app/c.py": "from rest import RestClient\n\n\nclass Base:\n    def __init__(self):\n"
                         "        self.api = RestClient('a')\n\n\nclass Cart(Base):\n    def __init__(self, client=None):\n"
                         "        super().__init__()\n        if client:\n            self.api = client\n\n"
                         "    def view(self):\n        return self.api.get('/cart')\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in clients(s, "app/c.py")] == [("GET", "/cart")]
