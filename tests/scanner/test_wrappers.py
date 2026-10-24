"""HTTP client wrappers: a function passing its own parameter to an HTTP client is a wrapper, and a call to it with a
path literal is a request (format.md § http clients), so a frontend's calls through its own API helper are found."""
from conftest import with_stack


from vizcode import structure


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
