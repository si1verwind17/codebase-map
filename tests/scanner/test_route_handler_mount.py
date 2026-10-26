"""Regex routes: the optional `handler` group (resolved by name) and `mount: true` entries."""
import pytest
from conftest import with_stack

from vizcode.scan import stack, structure

from helpers import write

EXPRESS = ("javascript:\n  routes:\n"
           "    - name: express\n      when: express\n      path: literal\n"
           "      regex: '\\b(?:app|router)\\.(?P<method>get|post)\\(\\s*[\"''](?P<path>[^\"'']+)[\"'']\\s*,\\s*(?P<handler>\\w+)'\n"
           "    - name: express-use\n      when: express\n      path: literal\n      mount: true\n"
           "      regex: '\\bapp\\.use\\(\\s*[\"''](?P<path>[^\"'']+)[\"'']\\s*,\\s*(?P<target>\\w+)'\n"
           "    - name: express-use-bare\n      when: express\n      path: literal\n      mount: true\n"
           "      regex: '\\bapp\\.use\\(\\s*[\"''](?P<path>[^\"'']+)[\"'']\\s*\\)'\n")
SRC = {
    "package.json": '{"name": "api"}\n',
    "src/app.js": "const express = require('express');\nconst app = express();\n"
                  "app.get('/orders', listOrders);\napp.post('/orders', missing);\n"
                  "app.get('/inline', function () {});\napp.use('/v1', router);\napp.use('/bare');\n",
    "src/handlers.js": "function listOrders() { return []; }\nmodule.exports = { listOrders };\n",
}


def build(make_repo, files=SRC, text=EXPRESS):
    repo = make_repo(files)
    with_stack(repo, text)
    return structure.build(repo, "docs/viz-code")


def test_handler_group_resolves_across_files_of_the_module(make_repo):
    s = build(make_repo)
    rs = {(r["method"], r["path"]): r["handler"] for r in s["facts"]["src/app.js"]["routes"]}
    assert rs[("GET", "/orders")] == ".::src/handlers.js#listOrders/0"
    assert all("handler_name" not in r for r in s["facts"]["src/app.js"]["routes"])
    # not found: the span rule's handler stays (the file node here, since no function surrounds the match); an
    # inline handler at the file's top is a node of its own
    assert rs[("POST", "/orders")] == ".::src/app.js" and rs[("GET", "/inline")] == ".::src/app.js#get_inline/0"


def test_same_file_beats_other_files(make_repo):
    twin = {**SRC, "src/app.js": SRC["src/app.js"] + "function listOrders() {}\n"}
    s = build(make_repo, twin)
    h = next(r["handler"] for r in s["facts"]["src/app.js"]["routes"] if r["path"] == "/orders" and r["method"] == "GET")
    assert h == ".::src/app.js#listOrders/0"


def test_two_candidates_in_one_level_is_ambiguous(make_repo):
    files = {"package.json": SRC["package.json"], "src/app.js": SRC["src/app.js"],
             "src/a.js": "function listOrders() {}\n", "src/b.js": "function listOrders() {}\n"}
    s = build(make_repo, files)
    rs = {(r["method"], r["path"]): r["handler"] for r in s["facts"]["src/app.js"]["routes"]}
    assert rs[("GET", "/orders")] == ".::src/app.js"   # the span rule's handler


def test_mounts_are_facts_not_routes(make_repo):
    s = build(make_repo)
    f = s["facts"]["src/app.js"]
    assert all(r["path"] not in ("/v1", "/bare") for r in f["routes"])
    assert [(m["path"], m["target"], m["line"]) for m in f["mounts"]] == [("/v1", "router", 6), ("/bare", None, 7)]
    md = structure.summary_md(s)
    assert "- **mounts:** /v1 → router (src/app.js:6); /bare (src/app.js:7)\n" in md
    assert md.index("- **routes:**") < md.index("- **mounts:**")
    pats = {p["name"]: p for p in s["stack"]["patterns"]}
    assert (pats["express-use"]["matches"], pats["express-use"]["mount"]) == (1, True)
    assert "- javascript express-use (stack.yaml): 1 mount in 1 file\n" in md
    assert "- javascript express (stack.yaml): 3 routes in 1 file\n" in md


def test_no_mounts_key_without_matches(make_repo):
    s = build(make_repo, {"package.json": SRC["package.json"], "src/a.js": "const express = require('express');\n"})
    assert "mounts" not in s["facts"]["src/a.js"]


@pytest.mark.parametrize("entry,reason", [
    ("mount: maybe\n      regex: '(?P<path>x)'", "mount must be true or false"),
    ("mount: true\n      regex: '(?P<path>x)(?P<method>y)'", "only path and target"),
    ("mount: true\n      regex: '(?P<target>x)'", "no path group"),
])
def test_mount_validation(tmp_path, entry, reason):
    text = f"javascript:\n  routes:\n    - name: m\n      path: literal\n      {entry}\n"
    with pytest.raises(stack.StackError, match=reason):
        stack.load(write(tmp_path, text))


def test_mount_needs_no_method(tmp_path):
    st = stack.load(write(tmp_path, "javascript:\n  routes:\n    - name: m\n      path: literal\n      mount: true\n"
                          "      regex: '(?P<path>x)'\n"))
    assert next(p for p in st.patterns if p.name == "m").mount is True



GO_MUX = ("go:\n  routes:\n    - name: mux\n      path: literal\n      method: GET\n"
          "      regex: '\\.HandleFunc\\(\\s*\"(?P<path>[^\"]*)\"\\s*,\\s*(?P<handler>[\\w.]+)\\s*\\)"
          "(?:\\.Methods\\((?P<methods>[^)]*)\\))?'\n"
          "    - name: verb-call\n      path: literal\n"
          "      regex: '\\.Add\\(\\s*(?P<method>[\\w.:]+)\\s*,\\s*\"(?P<path>[^\"]*)\"'\n")


def test_methods_given_as_qualified_constants(make_repo):
    # `http.MethodHead`, `HttpMethod.GET`, `Method::POST`: the last part names the verb, case-insensitively
    s = build(make_repo, {
        "go.mod": "module example.com/shop\n",
        "main.go": 'package main\n\nfunc main() {\n'
                   '\tr.HandleFunc("/cart", viewCart).Methods(http.MethodGet, http.MethodHead)\n'
                   '\tr.HandleFunc("/pay", pay).Methods("POST")\n'
                   '\tr.Add(HttpMethod.DELETE, "/cart")\n\tr.Add(Method::PATCH, "/cart")\n\tr.Add(get, "/x")\n}\n\n'
                   'func viewCart() {}\n\nfunc pay() {}\n'}, GO_MUX)
    got = sorted((r["method"], r["path"]) for r in s["facts"]["main.go"]["routes"])
    assert got == [("DELETE", "/cart"), ("GET", "/cart"), ("GET", "/x"), ("HEAD", "/cart"), ("PATCH", "/cart"),
                   ("POST", "/pay")]


def _paths(s, f):
    return sorted((r["method"], r["path"]) for r in s["facts"][f]["routes"])


def test_mount_prefix_composes_onto_routes_on_its_variable(make_repo):
    # a group bound to a variable: routes on that variable (and on groups made from it) take its prefix
    s = build(make_repo, {
        "go.mod": "module example.com/shop\n\nrequire github.com/gin-gonic/gin v1.9.0\n",
        "main.go": 'package main\n\nimport "github.com/gin-gonic/gin"\n\nfunc main() {\n\tr := gin.Default()\n'
                   '\tr.GET("/health", health)\n\tv1 := r.Group("/v1")\n\t{\n\t\tv1.GET("/orders/:id", getOrder)\n'
                   '\t\tadmin := v1.Group("/admin")\n\t\tadmin.POST("/orders", addOrder)\n\t}\n}\n\n'
                   'func health() {}\nfunc getOrder() {}\nfunc addOrder() {}\n'}, "")
    assert _paths(s, "main.go") == [("GET", "/health"), ("GET", "/v1/orders/{id}"), ("POST", "/v1/admin/orders")]
    assert [(m["path"], m.get("composed")) for m in s["facts"]["main.go"]["mounts"]] == [("/v1", 2), ("/admin", 1)]
    md = structure.summary_md(s)
    assert "- **mounts:** /v1 (main.go:8, composed onto 2 routes); /admin (main.go:11, composed onto 1 route)\n" in md


def test_mount_prefix_composes_inside_its_call_and_along_its_chain(make_repo):
    # routes registered inside the mount's own call (a closure, an inline router) or chained on what it returns
    s = build(make_repo, {
        "go.mod": "module example.com/shop\n",
        "main.go": 'package main\n\nimport "github.com/go-chi/chi/v5"\n\nfunc main() {\n\tr := chi.NewRouter()\n'
                   '\tr.Route("/orders", func(r chi.Router) {\n\t\t// don\'t cache\n\t\tr.Get("/", list)\n'
                   '\t\tr.Route("/{id:[0-9]+}", func(r chi.Router) {\n\t\t\tr.Get("/", get)\n\t\t})\n\t})\n'
                   '\tr.Mount("/admin", adminRouter())\n\tr.Get("/ping", ping)\n}\n\n'
                   'func list() {}\nfunc get() {}\nfunc ping() {}\n'}, "")
    assert _paths(s, "main.go") == [("GET", "/orders"), ("GET", "/orders/{id}"), ("GET", "/ping")]
    mounts = {m["path"]: m.get("composed") for m in s["facts"]["main.go"]["mounts"]}
    assert mounts == {"/orders": 2, "/{id}": 1, "/admin": None}


def test_mount_with_a_target_does_not_reach_the_chain_after_it(make_repo):
    # `.nest("/api", x)` returns the outer router: a route chained after it is not under /api
    stack_text = ("rust:\n  routes:\n    - name: route-to\n      path: literal\n"
                  "      regex: '\\.route\\(\\s*\"(?P<path>[^\"]*)\"\\s*,\\s*web::(?P<method>get|post)\\(\\)'\n")
    s = build(make_repo, {
        "Cargo.toml": '[package]\nname = "shop"\n',
        "src/main.rs": 'use axum::Router;\nuse actix_web::web;\n\nfn app() {\n'
                       '    Router::new().nest("/api", Router::new().route("/a", web::get().to(a))).route("/b", web::get().to(b));\n'
                       '    App::new().service(web::scope("/admin").route("/c", web::post().to(c))).route("/d", web::get().to(d));\n'
                       '}\n'}, stack_text)
    assert _paths(s, "src/main.rs") == [("GET", "/api/a"), ("GET", "/b"), ("GET", "/d"), ("POST", "/admin/c")]


@pytest.mark.parametrize("files,f,want", [
    ({"Api/Api.csproj": "<Project Sdk=\"Microsoft.NET.Sdk.Web\"></Project>\n",
      "Api/Program.cs": "var app = builder.Build();\nvar api = app.MapGroup(\"api/catalog\").WithTags(\"x\");\n"
                        "api.MapGet(\"/items/{id:int}\", GetItem);\napp.MapGet(\"/health\", Health);\n"},
     "Api/Program.cs", [("GET", "/api/catalog/items/{id}"), ("GET", "/health")]),
    ({"build.gradle.kts": "", "src/main/kotlin/App.kt":
      "import io.ktor.server.routing.*\n\nfun Application.module() {\n    routing {\n"
      "        route(\"/v1\") {\n            get(\"/orders\") { call.respond(1) }\n        }\n"
      "        get(\"/ping\") { call.respond(2) }\n    }\n}\n"},
     "src/main/kotlin/App.kt", [("GET", "/ping"), ("GET", "/v1/orders")]),
    ({"composer.json": "{}", "routes/api.php":
      "<?php\nuse Illuminate\\Support\\Facades\\Route;\n\nRoute::prefix('admin')->group(function () {\n"
      "    Route::get('/users', [UserController::class, 'index']);\n});\nRoute::get('/up', [Up::class, 'show']);\n"},
     "routes/api.php", [("GET", "/admin/users"), ("GET", "/up")]),
    ({"package.json": '{"name": "api"}\n', "src/orders.js":
      "const Router = require('@koa/router');\nconst router = new Router({ prefix: '/orders' });\n"
      "router.get('/:id', show);\nfunction show() {}\n"},
     "src/orders.js", [("GET", "/orders/{id}")]),
])
def test_mount_composition_in_other_languages(make_repo, files, f, want):
    s = build(make_repo, files, "")
    assert _paths(s, f) == want


def _handlers(s, f):
    return {(r["method"], r["path"]): r["handler"] for r in s["facts"][f]["routes"]}


def test_handler_follows_the_imports_and_prefers_a_free_function(make_repo):
    # two `set_email` in the crate: the one the routing file imports; `sign_out` is a free function and a method
    s = build(make_repo, {
        "Cargo.toml": '[package]\nname = "shop"\n',
        "src/lib.rs": "pub mod routes;\npub mod auth;\npub mod session;\npub mod startup;\n",
        "src/routes.rs": "pub fn set_email() {}\npub fn sign_out() {}\n",
        "src/auth.rs": "pub fn set_email(user: u32) {}\n",
        "src/session.rs": "pub struct Session;\nimpl Session {\n    pub fn sign_out(&self) {}\n}\n",
        "src/startup.rs": "use axum::Router;\nuse axum::routing::post;\nuse crate::routes::set_email;\n\n"
                          "pub fn run() -> Router {\n    Router::new()\n"
                          "        .route(\"/email\", post(set_email))\n"
                          "        .route(\"/signout\", post(sign_out))\n        .route(\"/gone\", post(nowhere))\n}\n",
    }, "")
    hs = _handlers(s, "src/startup.rs")
    assert hs[("POST", "/email")] == ".::src/routes.rs#set_email/0"
    assert hs[("POST", "/signout")] == ".::src/routes.rs#sign_out/0"
    # a name that resolves to nothing: the file, never `run`, the function that registers the routes
    assert hs[("POST", "/gone")] == ".::src/startup.rs"


def test_handler_nested_in_the_registering_function_becomes_a_node(make_repo):
    s = build(make_repo, {
        "package.json": '{"name": "api"}\n',
        "src/server.js": "const express = require('express');\n\nfunction serve() {\n  const app = express();\n"
                         "  const listOrders = async (req, res) => {\n    res.json(await db.query('SELECT id FROM orders'));\n"
                         "  };\n  app.get('/orders', listOrders);\n  app.listen(80);\n}\n",
    })
    h = _handlers(s, "src/server.js")[("GET", "/orders")]
    assert h == ".::src/server.js#serve.listOrders/2"
    node = next(n for n in s["nodes"] if n["id"] == h)
    assert (node["name"], node["parent"], node["line"], node["metrics"]["loc"]) == \
        ("listOrders", ".::src/server.js", 5, 3)
    calls = {c["callee"]: c["in"] for c in s["facts"]["src/server.js"]["calls"]}
    assert calls["db.query"] == h and calls["app.listen"] == ".::src/server.js#serve/0"
    assert [q["in"] for q in s["facts"]["src/server.js"]["sql"]] == [h]


FLASK_ROUTE = ("python:\n  routes:\n    - name: flask\n      path: literal\n      method: GET\n"
               "      regex: '@\\w+\\.route\\(\\s*[\"''](?P<path>[^\"'']*)[\"'']'\n")


def test_decorated_route_nested_in_a_factory_is_its_own_function(make_repo):
    s = build(make_repo, {
        "app/__init__.py": "",
        "app/main.py": "from fastapi import FastAPI\nfrom flask import Flask\n\n\ndef make_app():\n"
                       "    app = Flask(__name__)\n\n    @app.route('/chat')\n    def talk(q):\n        return answer(q)\n\n"
                       "    api = FastAPI()\n\n    @api.get('/health')\n    def health():\n        return 'ok'\n\n"
                       "    return app\n\n\ndef answer(q):\n    return q\n",
    }, FLASK_ROUTE)
    hs = _handlers(s, "app/main.py")
    assert hs == {("GET", "/chat"): "app::app.main#make_app.talk/1",
                  ("GET", "/health"): "app::app.main#make_app.health/0"}
    calls = {c["callee"]: c["in"] for c in s["facts"]["app/main.py"]["calls"]}
    assert calls["answer"] == "app::app.main#make_app.talk/1" and calls["Flask"] == "app::app.main#make_app/0"
    assert all("nested_handler" not in r for r in s["facts"]["app/main.py"]["routes"])


def test_a_path_after_a_name_and_a_plus_keeps_its_route(make_repo):
    # a generated chi router: `r.Get(options.BaseURL+"/trainer/calendar", wrapper.X)`; the head is a setting
    files = {"go.mod": "module shop\n",
             "ports/api.go": 'package ports\n\nimport "github.com/go-chi/chi/v5"\n\nfunc Handler(r chi.Router) {\n'
                             '\tr.Get(options.BaseURL+"/trainer/calendar", wrapper.GetHours)\n'
                             '\tr.Post(base + "/trainer/hours", wrapper.MakeHours)\n}\n'}
    s = structure.build(make_repo(files))
    got = [(r["method"], r["path"], r.get("after")) for r in s["facts"]["ports/api.go"]["routes"]]
    assert got == [("GET", "/trainer/calendar", "options.BaseURL"), ("POST", "/trainer/hours", "base")]
    assert "GET /trainer/calendar (after `options.BaseURL`) → " in structure.summary_md(s)


def test_a_qualified_handler_takes_the_class_named_like_its_qualifier(make_repo):
    # three same-file methods named X: the interface's, a stub's and the wrapper's; `wrapper.X` is the wrapper's
    files = {"go.mod": "module shop\n",
             "ports/api.go": 'package ports\n\nimport "github.com/go-chi/chi/v5"\n\n'
                             'type ServerInterface interface {\n\tGetHours(w W, r R)\n}\n\n'
                             'type Unimplemented struct{}\n\nfunc (_ Unimplemented) GetHours(w W, r R) {}\n\n'
                             'type ServerInterfaceWrapper struct {\n\tHandler ServerInterface\n}\n\n'
                             'func (siw *ServerInterfaceWrapper) GetHours(w W, r R) {\n\tsiw.Handler.GetHours(w, r)\n}\n\n'
                             'func Handler(r chi.Router, wrapper ServerInterfaceWrapper) {\n'
                             '\tr.Get("/hours", wrapper.GetHours)\n}\n'}
    s = structure.build(make_repo(files))
    assert [r["handler"] for r in s["facts"]["ports/api.go"]["routes"]] == [".::ports.ServerInterfaceWrapper#GetHours/2"]


def test_the_qualifier_breaks_a_tie_only_and_names_a_whole_word(make_repo):
    # the handler of the same file wins over a class elsewhere named like the qualifier; `h` names no class `OAuth`
    files = {"package.json": '{"name": "api", "dependencies": {"express": "4"}}\n',
             "src/app.ts": "import express from 'express'\nconst app = express()\nclass Handlers {\n  list() {}\n}\n"
                           "const controller = new Handlers()\napp.get('/users', controller.list)\n",
             "src/other.ts": "export class UserController {\n  list() {}\n}\n"}
    s = structure.build(make_repo(files))
    assert [r["handler"].rsplit("::", 1)[-1] for r in s["facts"]["src/app.ts"]["routes"]] == ["src.app.Handlers#list/0"]


def test_a_client_call_with_a_built_address_is_no_route_and_a_mount_keeps_its_head(make_repo):
    files = {"go.mod": "module shop\n",
             "svc/notify.go": 'package svc\n\nimport (\n\t"net/http"\n\t"github.com/go-chi/chi/v5"\n)\n\n'
                              'func Routes(r chi.Router) {\n\tr.Get("/health", health)\n}\n\n'
                              'func notify() {\n\thttp.Post(baseURL+"/hooks/notify", "application/json", nil)\n'
                              '\tapiClient.Get(base + "/x", nil)\n}\n',
             "package.json": '{"name": "api", "dependencies": {"express": "4"}}\n',
             "src/app.ts": "import express from 'express'\nimport users from './users'\nconst app = express()\n"
                           "app.use(BASE + '/api', users)\n",
             "src/users.ts": "import { Router } from 'express'\nconst router = Router()\nrouter.get('/me', me)\n"
                             "function me() {}\nexport default router\n"}
    s = structure.build(make_repo(files))
    assert [(r["method"], r["path"]) for r in s["facts"]["svc/notify.go"]["routes"]] == [("GET", "/health")]
    assert [(m["path"], m.get("after")) for m in s["facts"]["src/app.ts"]["mounts"]] == [("/api", "BASE")]
    assert "/api (after `BASE`) → users (src/app.ts:4" in structure.summary_md(s)
