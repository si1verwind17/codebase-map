"""The Go, C#, Rust, Ruby and PHP built-in packs (imports, annotated and regex routes, mounts, ORM tables), the Go
fixture and one small service per other language, mapped with packs only (no stack.yaml)."""
import pytest
import yaml
from conftest import ASPNET_SERVICE, AXUM_SERVICE, LARAVEL_SERVICE, SINATRA_SERVICE, with_stack

from vizcode import stack, structure

from helpers import routes, sinks, tables
from helpers import write

GO_ORDERS = ".::internal/orders.Handler"


def build(make_repo, files, name="demo"):
    return structure.build(make_repo(files, name=name), "docs/viz-code")


def mounts(s, f):
    return [(m["path"], m["target"], m["line"], m["framework"]) for m in s["facts"][f].get("mounts", [])]


def found(lang, src, imports):
    """(method, path, handler_name) of every regex route the language's pack finds in src."""
    return [(r["method"], r["path"], r.get("handler_name"), r["framework"])
            for r in stack.find_routes(stack.default(), lang, src, imports, [], "f")]


def found_mounts(lang, src, imports):
    return [(m["path"], m["target"], m["framework"]) for m in stack.find_mounts(stack.default(), lang, src, imports)]


def found_tables(lang, src, imports):
    return [(t["table"], t["pattern"]) for t in stack.find_tables(stack.default(), lang, src, imports, [], [], "f")]


# Go (net/http with Go 1.22 method patterns, pgx, resty) with packs only

def test_go_routes(go_repo):
    s = structure.build(go_repo, "docs/viz-code")
    main = ".::cmd/server/main.go"
    # `h.GetOrder` resolves by its last segment; an inline func keeps the function around the call; a handler
    # wrapped in a call (`http.HandlerFunc(metrics)`) is the wrapped name
    assert routes(s, "cmd/server/main.go") == [
        ("GET", "/orders/{id}", f"{GO_ORDERS}#GetOrder/2", 13, "net-http", "pack"),
        ("POST", "/orders", f"{GO_ORDERS}#CreateOrder/2", 14, "net-http", "pack"),
        ("ANY", "/healthz", f"{main}#main/0", 15, "net-http", "pack"),
        ("ANY", "/metrics", f"{main}#metrics/2", 16, "net-http", "pack")]
    for f in ("internal/orders/handler.go", "internal/pricing/client.go"):
        assert routes(s, f) == [], f


def test_go_sinks_and_stack_section(go_repo):
    s = structure.build(go_repo, "docs/viz-code")
    assert sinks(s, "cmd/server/main.go") == [("http", "net/http")]
    assert sinks(s, "internal/orders/handler.go") == [("http", "net/http"), ("sql-db", "github.com/jackc/pgx")]
    assert sinks(s, "internal/pricing/client.go") == [("http-out", "github.com/go-resty/resty")]
    assert [(q["reads"], q["in"]) for q in s["facts"]["internal/orders/handler.go"]["sql"]] == [
        (["orders"], f"{GO_ORDERS}#load/2")]
    assert s["stack"]["unrecognised"] == [] and s["stack"]["servers_without_routes"] == []
    assert "- go net-http (pack): 4 routes in 1 file\n" in structure.summary_md(s)


def test_go_import_kinds():
    st = stack.default()
    for target, kind in (("database/sql", "sql-db"), ("github.com/jackc/pgx/v5/pgxpool", "sql-db"),
                         ("gorm.io/gorm", "sql-db"), ("github.com/jmoiron/sqlx", "sql-db"),
                         ("github.com/IBM/sarama", "event"), ("github.com/segmentio/kafka-go", "event"),
                         ("github.com/rabbitmq/amqp091-go", "event"), ("github.com/redis/go-redis/v9", "cache"),
                         ("github.com/go-resty/resty/v2", "http-out"), ("net/http", "http"),
                         ("github.com/gin-gonic/gin", "http-in"), ("github.com/labstack/echo/v4", "http-in"),
                         ("github.com/go-chi/chi/v5", "http-in"), ("github.com/aws/aws-sdk-go-v2/service/s3", "cloud-sdk"),
                         ("cloud.google.com/go/storage", "cloud-sdk"), ("cloud.google.com/go/pubsub", "event"),
                         ("google.golang.org/grpc", "grpc")):
        assert [h["kind"] for h in stack.sink_kinds(st, "go", target)] == [kind], target
    assert stack.sink_kinds(st, "go", "net/url") == []


def test_go_gin_echo_chi():
    gin = ('r := gin.Default()\nv1 := r.Group("/v1")\nv1.GET("/orders/:id", auth, h.GetOrder)\n'
           'r.POST("/orders", func(c *gin.Context) {})\nr.Any("/ping", ping)\n')
    assert found("go", gin, ["github.com/gin-gonic/gin"]) == [
        ("GET", "/orders/{id}", "h.GetOrder", "gin"), ("POST", "/orders", None, "gin"), ("ANY", "/ping", "ping", "gin")]
    assert found_mounts("go", gin, ["github.com/gin-gonic/gin"]) == [("/v1", None, "gin-group")]
    echo = gin.replace("gin.Default()", "echo.New()").replace("*gin.Context", "echo.Context")
    assert [x[:3] for x in found("go", echo, ["github.com/labstack/echo/v4"])] == [
        x[:3] for x in found("go", gin, ["github.com/gin-gonic/gin"])]
    assert found_mounts("go", echo, ["github.com/labstack/echo/v4"]) == [("/v1", None, "echo-group")]
    chi = ('r := chi.NewRouter()\nr.Get("/orders/{id}", h.GetOrder)\nr.Delete("/orders/{id}", h.Drop)\n'
           'r.Route("/v1", func(r chi.Router) {})\nr.Mount("/admin", adminRouter())\n')
    assert found("go", chi, ["github.com/go-chi/chi/v5"]) == [
        ("GET", "/orders/{id}", "h.GetOrder", "chi"), ("DELETE", "/orders/{id}", "h.Drop", "chi")]
    assert found_mounts("go", chi, ["github.com/go-chi/chi/v5"]) == [
        ("/v1", None, "chi-route"), ("/admin", "adminRouter", "chi-mount")]


def test_go_negatives():
    """Look-alikes and missing imports give no route, mount or table."""
    http = ('q := r.URL.Query()\nq.Get("id")\nresp, _ := client.R().Get("/orders")\nh.Handle(event)\n'
            'mux.HandleFunc("orders", h)\nmux.HandleFunc(path, h)\n')
    assert found("go", http, ["net/http"]) == []
    assert found("go", 'mux.HandleFunc("/x", h)\n', ["github.com/gorilla/mux"]) == []
    gin = 'c.GET("/x", h)\nr.Group("/v1")\n'
    assert found("go", gin, ["net/http"]) == [] and found_mounts("go", gin, ["net/http"]) == []
    # gin and echo need the comma after the path (`c.GET("key")` reads a value)
    assert found("go", 'c.GET("/key")\n', ["github.com/gin-gonic/gin"]) == []
    assert found("go", 'c.GET("/key")\n', ["github.com/labstack/echo"]) == []
    # chi's verbs need a path starting with `/` and a handler argument; Route/Mount need the chi import
    chi = 'r.Get("id", x)\nv.Get("/a")\nr.Route("/v1", f)\nr.Mount("/a", b)\n'
    assert found("go", chi, ["github.com/go-chi/chi/v5"]) == []
    assert found_mounts("go", chi, ["net/http"]) == []
    # gorm models often import nothing: no `when`; the look-alikes (another method, a variable, no receiver,
    # another return type) give nothing
    gorm = ('func (Order) TableName() string {\n\treturn "orders"\n}\nfunc (Order) Name() string { return "x" }\n'
            'func (o *Item) TableName() string { return name }\nfunc TableName() string { return "free" }\n'
            'func (Line) TableName() any { return "lines" }\nfunc (l *Line) TableName() string { return "order_lines" }\n')
    assert found_tables("go", gorm, []) == [("orders", "gorm-table-name"), ("order_lines", "gorm-table-name")]


# C# (ASP.NET controllers and minimal APIs, EF Core)

def test_aspnet_service(make_repo):
    s = build(make_repo, ASPNET_SERVICE)
    ctrl = "Shop::Shop.Controllers.OrdersController"
    # a method template starting with `/` or `~/` overrides the controller prefix
    assert routes(s, "Shop/Controllers/OrdersController.cs") == [
        ("GET", "/api/Orders/{id}", f"{ctrl}#Get/1", 10, "aspnet", "pack"),
        ("POST", "/api/Orders", f"{ctrl}#Create/0", 13, "aspnet", "pack"),
        ("GET", "/health", f"{ctrl}#Health/0", 16, "aspnet", "pack"),
        ("DELETE", "/admin/orders/{id}", f"{ctrl}#Purge/1", 19, "aspnet", "pack")]
    assert [(r["method"], r["path"], r["line"], r["framework"]) for r in s["facts"]["Shop/Program.cs"]["routes"]] == [
        ("GET", "/ping", 5, "aspnet-minimal")]
    assert sinks(s, "Shop/Controllers/OrdersController.cs") == [("http-in", "Microsoft.AspNetCore.Mvc")]
    assert sinks(s, "Shop/Program.cs") == [("http-in", "Microsoft.AspNetCore.Builder")]
    assert sinks(s, "Shop/Data/ShopDb.cs") == [("sql-db", "Microsoft.EntityFrameworkCore")]
    assert tables(s, "Shop/Data/ShopDb.cs") == [
        ("orders", 9, "Shop::Shop.Data.ShopDb#OnModelCreating/1", "access", "ef-to-table")]
    # Microsoft.Extensions (logging, DI, configuration) is the framework's wiring
    assert s["stack"]["unrecognised"] == [] and s["stack"]["servers_without_routes"] == []


def test_aspnet_absolute_templates_and_method_route(make_repo):
    src = ("using Microsoft.AspNetCore.Mvc;\n\nnamespace Shop;\n\n[Route(\"v1/[controller]\")]\n"
           "public class ItemsController : ControllerBase {\n"
           "  [HttpGet, Route(\"/all\")]\n  public void All() {}\n"
           "  [HttpPut(\"[action]\")]\n  public void Touch() {}\n"
           "  [HttpPatch(\"~/x\")]\n  public void X() {}\n"
           "  [HttpHead(\"a/~/b\")]\n  public void Y() {}\n}\n")
    s = build(make_repo, {"Shop/Shop.csproj": "<Project/>\n", "Shop/ItemsController.cs": src})
    assert [(r["method"], r["path"]) for r in s["facts"]["Shop/ItemsController.cs"]["routes"]] == [
        ("GET", "/all"), ("PUT", "/v1/Items/Touch"), ("PATCH", "/x"), ("HEAD", "/v1/Items/a/~/b")]


def test_annotated_absolute_option(tmp_path):
    st = stack.load(write(tmp_path, "csharp:\n  routes:\n    - {name: a, form: annotated, verbs: {HttpGet: GET}, "
                                    "prefix: [Route], absolute: ['/', '~/']}\n"))
    pat = next(p for p in st.patterns if p.name == "a")
    assert pat.absolute == ("/", "~/")
    # Spring joins a leading `/` (no absolute option)
    assert next(p for p in st.patterns if p.name == "spring-web").absolute == ()
    for bad, why in (("absolute: '/'", "absolute must be a list of path starts"),
                     ("absolute: ['']", "absolute must be a list of path starts"),
                     ("absolute: [3]", "absolute must be a list of path starts")):
        with pytest.raises(stack.StackError, match=why):
            stack.load(write(tmp_path, f"csharp:\n  routes:\n    - {{name: b, form: annotated, verbs: {{G: GET}}, {bad}}}\n"))


def test_aspnet_minimal_api_and_tables():
    src = ('var app = builder.Build();\nvar orders = app.MapGroup("/orders");\norders.MapGet("/{id}", GetOrder);\n'
           'app.MapPost("/orders", (Order o) => Results.Ok());\napp.MapDelete(@"/orders/{id}", Drop);\n')
    assert found("csharp", src, ["Microsoft.AspNetCore.Builder"]) == [
        ("GET", "/{id}", "GetOrder", "aspnet-minimal"), ("POST", "/orders", None, "aspnet-minimal"),
        ("DELETE", "/orders/{id}", "Drop", "aspnet-minimal")]
    assert found_mounts("csharp", src, []) == [("/orders", None, "aspnet-map-group")]
    ef = ('[Table("order_lines", Schema = "s")]\npublic class Line {}\n[Key, Table("x")]\nclass Y {}\n'
          'b.Entity<Order>().ToTable("orders");\n')
    assert found_tables("csharp", ef, ["System.ComponentModel.DataAnnotations.Schema"]) == [
        ("order_lines", "ef-table-attribute"), ("x", "ef-table-attribute")]
    assert found_tables("csharp", ef, ["Microsoft.EntityFrameworkCore"]) == [("orders", "ef-to-table")]


def test_csharp_negatives():
    """Look-alikes give nothing."""
    # minimal APIs run without `when` (implicit usings: Program.cs names nothing); the look-alikes give nothing
    src = ('app.MapGet("/ping", h);\nconfig.Map("/x");\ndict.MapGetter("/y", h);\nvar g = app.MapGroup("/g");\n'
           'cfg.MapGet("/one");\nm.MapGet(path, h);\nm.MapPost($"/i/{x}", h);\nMapGet("/bare", h);\n'
           'm.MapPut("has space", h);\nm.MapHead("/h", h);\n')
    assert found("csharp", src, []) == [("GET", "/ping", "h", "aspnet-minimal")]
    # MapGroup too (no `when`): a receiver, one plain string literal argument
    assert found_mounts("csharp", src, []) == [("/g", None, "aspnet-map-group")]
    groups = ('MapGroup("/bare");\nm.MapGroup(prefix);\nm.MapGroup($"/v{x}");\nm.MapGroupX("/a");\n'
              'm.MapGroup("has space");\nm.MapGroup("/a", extra);\nm.MapGroups("/b");\n')
    assert found_mounts("csharp", groups, []) == []
    tbl = '[Table("x")]\nclass A {}\nb.ToTable("y");\nvar t = new Table("z");\n'
    assert found_tables("csharp", tbl, ["System.Linq"]) == []
    assert found_tables("csharp", tbl, ["System.ComponentModel.DataAnnotations.Schema"]) == [("x", "ef-table-attribute")]


def test_csharp_import_kinds():
    st = stack.default()
    for target, kind in (("Microsoft.EntityFrameworkCore", "sql-db"), ("Dapper", "sql-db"), ("Npgsql", "sql-db"),
                         ("Microsoft.Data.SqlClient", "sql-db"), ("System.Data.SqlClient", "sql-db"),
                         ("Confluent.Kafka", "event"), ("RabbitMQ.Client", "event"), ("StackExchange.Redis", "cache"),
                         ("System.Net.Http", "http-out"), ("System.Net.Http.Json", "http-out"),
                         ("Microsoft.AspNetCore.Mvc", "http-in"), ("Microsoft.AspNetCore.Builder", "http-in"),
                         ("Microsoft.AspNetCore.SignalR", "ws"), ("Microsoft.Extensions.Http", "http-out"),
                         ("Microsoft.Extensions.Http.Resilience", "http-out"),
                         ("Microsoft.Extensions.Caching.StackExchangeRedis", "cache"),
                         ("Microsoft.Extensions.Caching.SqlServer", "cache"),
                         ("Microsoft.Extensions.Caching.Cosmos", "cache"), ("Microsoft.Extensions.Azure", "cloud-sdk"),
                         ("Amazon.S3", "cloud-sdk"), ("Google.Cloud.Storage.V1", "cloud-sdk"),
                         ("Google.Cloud.PubSub.V1", "event"), ("Grpc.Net.Client", "grpc")):
        assert [h["kind"] for h in stack.sink_kinds(st, "csharp", target)] == [kind], target
    # imports win over the System ignore; the framework wiring is ignored
    for target in ("System.Linq", "Microsoft.AspNetCore.Http", "Microsoft.AspNetCore.Authorization",
                   "Microsoft.Extensions.Logging", "Microsoft.Extensions.DependencyInjection",
                   "Microsoft.Extensions.Caching.Memory"):
        assert stack.covered(st, "csharp", target) and stack.sink_kinds(st, "csharp", target) == [], target
    assert not stack.covered(st, "csharp", "Newtonsoft.Json")


# Rust (Axum, actix-web, sqlx)

def test_axum_service(make_repo):
    s = build(make_repo, AXUM_SERVICE)
    # `handlers::get_order` resolves by its last segment
    assert routes(s, "src/main.rs") == [
        ("GET", "/orders/{id}", ".::src/handlers.rs#get_order/1", 7, "axum", "pack"),
        ("POST", "/orders", ".::src/main.rs#create_order/0", 8, "axum", "pack")]
    assert mounts(s, "src/main.rs") == [("/admin", "admin", 9, "axum-nest")]
    assert sinks(s, "src/handlers.rs") == [("sql-db", "sqlx")]
    assert set(sinks(s, "src/main.rs")) == {("http-in", "axum")}
    assert s["stack"]["unrecognised"] == [] and s["stack"]["servers_without_routes"] == []


def test_axum_forms_and_actix():
    axum = ('Router::new()\n  .route("/a", axum::routing::delete(drop))\n  .route("/b", any(h))\n'
            '  .route("/c", get(|| async { "x" }))\n  .route("/d", get(move |s| f(s)))\n')
    assert found("rust", axum, ["axum::Router"]) == [
        ("DELETE", "/a", "drop", "axum"), ("ANY", "/b", "h", "axum"), ("GET", "/c", None, "axum"),
        ("GET", "/d", None, "axum")]
    actix = ('#[get("/orders/{id}")]\nasync fn get_order() {}\n#[actix_web::post("/orders")]\nasync fn create() {}\n'
             'App::new().service(web::scope("/v1").service(get_order));\n')
    imports = ["actix_web::get", "actix_web::web"]
    assert found("rust", actix, imports) == [("GET", "/orders/{id}", None, "actix"), ("POST", "/orders", None, "actix")]
    assert found_mounts("rust", actix, imports) == [("/v1", None, "actix-scope")]
    # the attribute takes the function below it
    spans = [(2, 2, "f#get_order/0"), (4, 4, "f#create/0")]
    got = stack.find_routes(stack.default(), "rust", actix, imports, spans, "f")
    assert [r["handler"] for r in got] == ["f#get_order/0", "f#create/0"]


def test_actix_builder_routes():
    """`.route(path, get().to(h))`, a `resource(path)` whose chained `.route(get().to(h))` take its path, and an
    empty path on a scope: each a route with its handler, composed onto the scopes around it."""
    src = ('cfg.service(\n  scope("/api/v4")\n    .service(\n      scope("/site")\n'
           '        .route("", get().to(get_site))\n        .route("/icon", web::post().to(site::upload_icon)),\n'
           '    )\n    .service(\n      resource("/search")\n        .wrap(rate_limit.search())\n'
           '        .route(get().to(search))\n        .route(post().to(search_post)),\n    ),\n);\n')
    imports = ["actix_web::web", "actix_web::web::scope"]
    st = stack.default()
    mounts = stack.find_mounts(st, "rust", src, imports)
    got = stack.find_routes(st, "rust", src, imports, [], "f", mounts)
    assert [(r["method"], r["path"], r.get("handler_name")) for r in got] == [
        ("GET", "/api/v4/site", "get_site"), ("POST", "/api/v4/site/icon", "site::upload_icon"),
        ("GET", "/api/v4/search", "search"), ("POST", "/api/v4/search", "search_post")]


def test_an_actix_resource_route_needs_a_resource_path(make_repo):
    files = {"Cargo.toml": "[package]\nname = \"app\"\n",
             "src/main.rs": "use actix_web::web;\n\nfn config(cfg: &mut web::ServiceConfig) {\n"
                            "    cfg.service(web::resource([\"/a\", \"/b\"]).route(web::get().to(list)));\n}\n"
                            "async fn list() {}\n"}
    s = build(make_repo, files)
    assert s["facts"]["src/main.rs"].get("routes", []) == []


def test_rust_negatives():
    """Look-alikes give nothing."""
    src = ('.route("/a", get(h))\n.nest("/n", r)\n#[get("/x")]\nfn x() {}\nweb::scope("/v1")\n'
           'map.route("k")\n#[test]\nfn t() {}\n')
    assert found("rust", src, ["std::collections"]) == [] and found_mounts("rust", src, ["serde"]) == []
    assert [x[1] for x in found("rust", src, ["axum"])] == ["/a"]
    assert [x[1] for x in found("rust", src, ["actix_web"])] == ["/x"]
    # rocket shares actix's attribute shape: no actix_web import, no route
    assert found("rust", '#[get("/r")]\nfn r() {}\n', ["rocket"]) == []


def test_rust_import_kinds():
    st = stack.default()
    for target, kind in (("sqlx::PgPool", "sql-db"), ("diesel::prelude", "sql-db"), ("tokio_postgres::Client", "sql-db"),
                         ("rdkafka::producer", "event"), ("lapin::Channel", "event"), ("redis::Commands", "cache"),
                         ("reqwest::Client", "http-out"), ("axum::Router", "http-in"), ("actix_web::App", "http-in"),
                         ("aws_sdk_s3::Client", "cloud-sdk"), ("aws_config::load_from_env", "cloud-sdk")):
        assert [h["kind"] for h in stack.sink_kinds(st, "rust", target)] == [kind], target


# Ruby (Sinatra, Rails routes, ActiveRecord)

def test_sinatra_service(make_repo):
    s = build(make_repo, SINATRA_SERVICE)
    # a Sinatra block is inline: the handler is the file, never the `def` below
    assert routes(s, "app.rb") == [("GET", "/orders/{id}", ".::_root_/app.rb", 6, "sinatra", "pack"),
                                   ("POST", "/orders", ".::_root_/app.rb", 10, "sinatra", "pack")]
    assert sinks(s, "app.rb") == [("http-in", "sinatra"), ("sql-db", "pg")]
    assert s["stack"]["unrecognised"] == [] and s["stack"]["servers_without_routes"] == []


def test_rails_routes(make_repo):
    files = {"Gemfile": "gem \"rails\"\n",
             "config/application.rb": "require \"rails/all\"\n\nmodule Shop\n  class Application < Rails::Application\n"
                                      "  end\nend\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  get \"/orders/:id\", to: \"orders#show\"\n"
                                 "  post 'orders', to: 'admin/orders#create'\n  resources :users\n"
                                 "  get \"/health\"\nend\n\ndef unrelated\nend\n",
             "app/controllers/orders_controller.rb": "class OrdersController < ApplicationController\n  def show\n"
                                                    "  end\nend\n"}
    s = build(make_repo, files)
    # routes.rb imports nothing: `orders#show` is the controller's action; where the action is not in the repo
    # (`admin/orders#create`, the users actions) the handler is the file
    assert routes(s, "config/routes.rb") == [
        ("GET", "/orders/{id}", ".::app/controllers.OrdersController#show/0", 2, "rails", "pack"),
        ("POST", "/orders", ".::config/routes.rb", 3, "rails", "pack"),
        *[(m, p, ".::config/routes.rb", 4, "rails-resources", "pack") for m, p in (
            ("GET", "/users"), ("GET", "/users/new"), ("POST", "/users"), ("GET", "/users/{id}"),
            ("GET", "/users/{id}/edit"), ("PATCH", "/users/{id}"), ("PUT", "/users/{id}"), ("DELETE", "/users/{id}"))]]
    assert sinks(s, "config/application.rb") == [("http-in", "rails")]
    assert s["stack"]["servers_without_routes"] == []


def test_rails_resources_are_handled_by_their_controller_actions(make_repo):
    files = {"Gemfile": "gem \"rails\"\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  resources :orders, only: [:index, :show]\n"
                                 "  resources :invoices, only: [:index]\n  resource :profile, only: :show\nend\n",
             "app/controllers/orders_controller.rb": "class OrdersController < ApplicationController\n"
                                                    "  def index\n  end\n\n  def show\n  end\nend\n",
             "app/controllers/profiles_controller.rb": "class ProfilesController < ApplicationController\n"
                                                      "  def show\n  end\nend\n"}
    s = build(make_repo, files)
    ctl = ".::app/controllers."
    assert routes(s, "config/routes.rb") == [
        ("GET", "/orders", f"{ctl}OrdersController#index/0", 2, "rails-resources", "pack"),
        ("GET", "/orders/{id}", f"{ctl}OrdersController#show/0", 2, "rails-resources", "pack"),
        ("GET", "/invoices", ".::config/routes.rb", 3, "rails-resources", "pack"),   # no InvoicesController
        ("GET", "/profile", f"{ctl}ProfilesController#show/0", 4, "rails-resource", "pack")]
    assert not any("handler_class" in r or "handler_method" in r for r in s["facts"]["config/routes.rb"]["routes"])


def test_a_controller_name_shared_by_two_namespaces_is_picked_by_the_route_namespace(make_repo):
    ctl = "class OrdersController < ApplicationController\n  def create\n  end\n\n  def index\n  end\nend\n"
    files = {"Gemfile": "gem \"rails\"\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  post 'orders', to: 'admin/orders#create'\n"
                                 "  resources :orders, only: [:index]\nend\n",
             "app/controllers/orders_controller.rb": ctl,
             "app/controllers/admin/orders_controller.rb": "module Admin\n  " + ctl.replace("\n", "\n  ") + "\nend\n"}
    s = build(make_repo, files)
    rails = [r for r in s["facts"]["config/routes.rb"]["routes"] if r["framework"] == "rails"]
    assert [r["handler"] for r in rails] == [".::Admin.OrdersController#create/0"]
    # `resources :orders` names no namespace: two OrdersController classes, so the handler stays the file
    res = [r for r in s["facts"]["config/routes.rb"]["routes"] if r["framework"] == "rails-resources"]
    assert [r["handler"] for r in res] == [".::config/routes.rb"]


def test_a_route_naming_a_namespace_never_takes_the_top_level_controller(make_repo):
    files = {"Gemfile": "gem \"rails\"\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  post 'orders', to: 'admin/orders#create'\nend\n",
             "app/controllers/orders_controller.rb": "class OrdersController < ApplicationController\n"
                                                    "  def create\n  end\nend\n"}
    s = build(make_repo, files)
    assert [r["handler"] for r in s["facts"]["config/routes.rb"]["routes"]] == [".::config/routes.rb"]


def test_a_compact_namespaced_controller_is_found(make_repo):
    files = {"Gemfile": "gem \"rails\"\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  post 'orders', to: 'admin/orders#create'\n"
                                 "  resources :invoices, only: [:index]\nend\n",
             "app/controllers/admin/orders_controller.rb": "class Admin::OrdersController < ApplicationController\n"
                                                          "  def create\n  end\nend\n",
             "app/controllers/billing/invoices_controller.rb": "class Billing::InvoicesController < ApplicationController\n"
                                                              "  def index\n  end\nend\n"}
    s = build(make_repo, files)
    got = [(r["path"], r["handler"]) for r in s["facts"]["config/routes.rb"]["routes"]]
    assert [h.split("#")[-1] for _, h in got] == ["create/0", "index/0"]
    assert "Admin.OrdersController" in got[0][1] and "Billing.InvoicesController" in got[1][1]


def test_a_resource_naming_another_controller_keeps_the_file(make_repo):
    ctl = "class OrdersController < ApplicationController\n  def index\n  end\nend\n"
    files = {"Gemfile": "gem \"rails\"\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  resources :orders, controller: 'purchases', only: :index\n"
                                 "  resources :orders, :module => 'shop', only: :index\n"
                                 "  resource :orders, only: :index, controller: \"purchases\"\nend\n",
             "app/controllers/orders_controller.rb": ctl}
    s = build(make_repo, files)
    assert {r["handler"] for r in s["facts"]["config/routes.rb"]["routes"]} == {".::config/routes.rb"}


def test_handler_templates_shape():
    st = stack.load(None)
    ok = ("ruby:\n  routes:\n    - {name: r, regex: '^res :(?P<path>\\w+)', expand: {index: GET},"
          " handler_class: '{path|camel}_x', handler_method: 'do_{action}'}\n")
    stack._read(st, "stack.yaml", yaml.safe_load(ok), "stack")
    assert [(r["handler_class"], r["handler_method"]) for r in stack.find_routes(st, "ruby", "res :line_items\n", [], [], "f")
            if r["framework"] == "r"] == [("LineItems_x", "do_index")]
    for bad, why in (("method: GET, handler_class: X", "go together"),
                     ("method: GET, handler_class: '{nope}', handler_method: x", "template field 'nope' is not a regex group"),
                     ("method: GET, handler_class: '{path|upper}', handler_method: x", "unknown template filter 'upper'"),
                     ("method: GET, handler_class: X, handler_method: '{action}'", "'action' is not a regex group"),
                     ("mount: true, handler_class: X, handler_method: y", "a mount has no handler_class")):
        doc = "ruby:\n  routes:\n    - {name: r, regex: '^res :(?P<path>\\w+)', " + bad + "}\n"
        with pytest.raises(stack.StackError, match=why):
            stack._read(stack.load(None), "stack.yaml", yaml.safe_load(doc), "stack")


def test_ruby_negatives_and_tables():
    """Rails needs `to: "c#a"`; Sinatra needs its import and a block; tables need ActiveRecord."""
    src = ('get "/x"\nget "/y", to: redirect("/z")\nget "/w", to: "nohash"\nclient.get "/v", to: "a#b"\n'
           'cache.get("/k") do\nend\n')
    assert found("ruby", src, []) == []
    assert found("ruby", 'get "/s" do\nend\n', ["json"]) == []
    assert found("ruby", 'get "/s" do\nend\nget("/t") { 1 }\n', ["sinatra/base"]) == [
        ("GET", "/s", None, "sinatra"), ("GET", "/t", None, "sinatra")]
    model = 'class Order < ActiveRecord::Base\n  self.table_name = "legacy_orders"\nend\n'
    assert found_tables("ruby", model, ["active_record"]) == [("legacy_orders", "active-record-table-name")]
    # a Rails model requires nothing: no `when`; the look-alikes give nothing
    look = ('  self.table_name_prefix = "x_"\n  other.table_name = "o"\n  # self.table_name = "c"\n'
            '  self.table_name = name\n  self.table_name == "eq"\n')
    assert found_tables("ruby", model + look, []) == [("legacy_orders", "active-record-table-name")]


def test_ruby_import_kinds():
    st = stack.default()
    for target, kind in (("active_record", "sql-db"), ("pg", "sql-db"), ("mysql2", "sql-db"), ("sidekiq", "event"),
                         ("sidekiq/web", "event"), ("kafka", "event"), ("bunny", "event"), ("redis", "cache"),
                         ("faraday", "http-out"), ("httparty", "http-out"), ("net/http", "http-out"),
                         ("sinatra/base", "http-in"), ("rails/all", "http-in"), ("action_controller/railtie", "http-in")):
        assert [h["kind"] for h in stack.sink_kinds(st, "ruby", target)] == [kind], target


# PHP (Laravel, Symfony, Eloquent, Doctrine)

def test_laravel_service(make_repo):
    s = build(make_repo, LARAVEL_SERVICE)
    ctrl = ".::App\\Http\\Controllers.OrderController"
    assert routes(s, "routes/api.php") == [
        ("GET", "/orders/{id}", f"{ctrl}#show/1", 6, "laravel", "pack"),
        ("POST", "/orders", f"{ctrl}#store/0", 7, "laravel", "pack"),
        ("DELETE", "/v1/orders/{id}", f"{ctrl}#destroy/1", 10, "laravel", "pack"),
        ("GET", "/sync", ".::routes/api.php", 8, "laravel-match", "pack"),
        ("POST", "/sync", ".::routes/api.php", 8, "laravel-match", "pack")]
    assert mounts(s, "routes/api.php") == [("/v1", None, 9, "laravel-prefix")]
    assert sinks(s, "routes/api.php") == [("http-in", "Illuminate\\Support\\Facades\\Route")]
    assert sinks(s, "app/Http/Controllers/OrderController.php") == [("sql-db", "Illuminate\\Support\\Facades\\DB")]
    assert tables(s, "app/Models/Order.php") == [("orders", 9, ".::App\\Models.Order", "defined", "eloquent-table")]
    assert s["stack"]["unrecognised"] == [] and s["stack"]["servers_without_routes"] == []


def test_an_empty_route_path_is_the_mount_path(make_repo):
    src = ("<?php\n\nuse Illuminate\\Support\\Facades\\Route;\n\n"
           "Route::prefix('v1')->group(function () {\n    Route::get('', fn () => 1);\n"
           "    Route::post(\"\", fn () => 2);\n});\nRoute::get('', fn () => 3);\n"
           "Route::prefix('')->group(fn () => 4);\n")
    s = build(make_repo, {"composer.json": LARAVEL_SERVICE["composer.json"], "routes/api.php": src})
    assert [r[:2] for r in routes(s, "routes/api.php")] == [("GET", "/v1"), ("POST", "/v1"), ("GET", "/")]
    assert mounts(s, "routes/api.php") == [("/v1", None, 5, "laravel-prefix")]


def test_laravel_routes_file_without_a_use_line(make_repo):
    files = {**LARAVEL_SERVICE,
             "routes/api.php": LARAVEL_SERVICE["routes/api.php"].replace("use Illuminate\\Support\\Facades\\Route;\n", "")}
    assert "use Illuminate" not in files["routes/api.php"]
    s = build(make_repo, files)
    assert [r[:2] for r in routes(s, "routes/api.php")] == [
        ("GET", "/orders/{id}"), ("POST", "/orders"), ("DELETE", "/v1/orders/{id}"), ("GET", "/sync"), ("POST", "/sync")]
    assert mounts(s, "routes/api.php") == [("/v1", None, 8, "laravel-prefix")]


def test_symfony_and_doctrine(make_repo):
    ctrl = ("<?php\n\nnamespace App\\Controller;\n\nuse Symfony\\Bundle\\FrameworkBundle\\Controller\\AbstractController;\n"
            "use Symfony\\Component\\Routing\\Attribute\\Route;\n\n#[Route('/stock')]\n"
            "class StockController extends AbstractController\n{\n"
            "    #[Route('/{sku}', name: 'stock_show', methods: ['GET', 'HEAD'])]\n    public function show(string $sku) {}\n\n"
            "    #[Route(path: '/', methods: 'POST')]\n    public function add() {}\n\n"
            "    #[Route('/any')]\n    public function any() {}\n}\n")
    entity = ("<?php\n\nnamespace App\\Entity;\n\nuse Doctrine\\ORM\\Mapping as ORM;\n\n"
              "#[ORM\\Entity]\n#[ORM\\Table(name: 'stock_items')]\nclass StockItem\n{\n}\n")
    s = build(make_repo, {"composer.json": "{}\n", "src/Controller/StockController.php": ctrl,
                          "src/Entity/StockItem.php": entity})
    c = ".::App\\Controller.StockController"
    assert routes(s, "src/Controller/StockController.php") == [
        ("GET", "/stock/{sku}", f"{c}#show/1", 11, "symfony", "pack"),
        ("HEAD", "/stock/{sku}", f"{c}#show/1", 11, "symfony", "pack"),
        ("POST", "/stock", f"{c}#add/0", 14, "symfony", "pack"),
        ("ANY", "/stock/any", f"{c}#any/0", 17, "symfony", "pack")]
    assert sinks(s, "src/Controller/StockController.php") == [("http-in", "Symfony\\Component\\Routing")]
    assert tables(s, "src/Entity/StockItem.php") == [
        ("stock_items", 8, ".::App\\Entity.StockItem", "defined", "doctrine-table")]
    assert s["stack"]["unrecognised"] == []


def test_rails_resources_expand_to_their_actions():
    plural = [("GET", "/users", None, "rails-resources"), ("GET", "/users/new", None, "rails-resources"),
              ("POST", "/users", None, "rails-resources"), ("GET", "/users/{id}", None, "rails-resources"),
              ("GET", "/users/{id}/edit", None, "rails-resources"), ("PATCH", "/users/{id}", None, "rails-resources"),
              ("PUT", "/users/{id}", None, "rails-resources"), ("DELETE", "/users/{id}", None, "rails-resources")]
    assert found("ruby", "  resources :users\n", []) == plural
    assert found("ruby", "resources(:users, only: [:index, :show])\n", []) == [plural[0], plural[3]]
    assert found("ruby", "  resources :users, only: %i[create destroy] do\n", []) == [plural[2], plural[7]]
    assert found("ruby", "  resources :users, except: :destroy\n", []) == plural[:7]
    assert found("ruby", "  resources :users, only: %w[index show]\n", []) == [plural[0], plural[3]]
    assert found("ruby", "  resources :users, :only => [:index], :param => :slug\n", []) == [plural[0]]
    assert [r[:2] for r in found("ruby", "  resources :articles, param: :slug, only: [:show]\n", [])] == [
        ("GET", "/articles/{slug}")]
    assert [r[:2] for r in found("ruby", "  resources :articles, only: [:show, :index], param: :slug, except: :index\n",
                                 [])] == [("GET", "/articles/{slug}")]
    assert [r[:2] for r in found("ruby", "  resource :profile, except: [:new, :edit]\n", [])] == [
        ("POST", "/profile"), ("GET", "/profile"), ("PATCH", "/profile"), ("PUT", "/profile"), ("DELETE", "/profile")]
    look = "  # resources :old\n  x.resources :users\n  @resources = :users\n  resources_for :users\n"
    assert found("ruby", look, []) == []


def test_expand_entry_shape():
    ok = "ruby:\n  routes:\n    - {name: r, regex: '^res :(?P<path>\\w+)', expand: {index: GET, update: [PATCH /:id, PUT /:id]}}\n"
    st = stack.default()
    stack._read(st, "stack.yaml", yaml.safe_load(ok), "stack")
    assert [(r["method"], r["path"]) for r in stack.find_routes(st, "ruby", "res :a\n", [], [], "f")
            if r["framework"] == "r"] == [("GET", "/a"), ("PATCH", "/a/{id}"), ("PUT", "/a/{id}")]
    for bad, why in (("expand: [GET]", "expand must map"), ("expand: {index: 'GET x'}", "expand must map"),
                     ("expand: {index: GET}, mount: true", "a mount has no expand")):
        doc = "ruby:\n  routes:\n    - {name: r, regex: '^res :(?P<path>\\w+)', " + bad + "}\n"
        with pytest.raises(stack.StackError, match=why):
            stack._read(stack.default(), "stack.yaml", yaml.safe_load(doc), "stack")


def test_php_negatives_and_tables():
    """Look-alikes give nothing."""
    # a routes file may call the global `Route` alias without a `use`: the Route patterns run without `when`
    route = "Route::get('/x', [C::class, 'a']);\nRoute::match(['get'], '/m', h);\n" \
            "Route::middleware(['auth'])->prefix('v1');\n"
    assert found("php", route, []) == [("GET", "/x", "a", "laravel"), ("GET", "/m", None, "laravel-match")]
    assert found_mounts("php", route, []) == [("/v1", None, "laravel-prefix")]
    look = "$cache->get('/x', 1);\nRouter::get('/y', h);\n$r->prefix('/p');\nConfig::get('app.name');\n" \
           "$q->prefix('t_');\nMyRoute::get('/z', h);\n"
    assert found("php", look, ["Illuminate\\Support\\Facades\\Route"]) == []
    assert found_mounts("php", look, ["Illuminate\\Support\\Facades\\Route"]) == []
    assert found("php", "Route::any('/a', 'C@a');\nRoute::match(['put', 'patch'], '/b', [C::class, 'b']);\n",
                 ["Illuminate\\Support\\Facades\\Route"]) == [
        ("ANY", "/a", None, "laravel"), ("PUT", "/b", "b", "laravel-match"), ("PATCH", "/b", "b", "laravel-match")]
    model = "class A extends Model {\n    protected $table = 'as';\n    protected string $table2 = 'no';\n}\n"
    assert found_tables("php", model, ["Illuminate\\Database\\Eloquent\\Model"]) == [("as", "eloquent-table")]
    assert found_tables("php", model, ["Doctrine\\ORM\\Mapping"]) == []
    doctrine = "/** @ORM\\Table(name=\"legacy\") */\n#[ORM\\Table(name: 'new', schema: 's')]\n#[ORM\\Index(name: 'ix')]\n"
    assert found_tables("php", doctrine, ["Doctrine\\ORM\\Mapping"]) == [("legacy", "doctrine-table"),
                                                                       ("new", "doctrine-table")]
    assert found_tables("php", doctrine, ["Illuminate\\Database"]) == []


def test_php_import_kinds():
    st = stack.default()
    for target, kind in (("PDO", "sql-db"), ("Doctrine\\DBAL\\Connection", "sql-db"), ("Doctrine\\ORM\\Mapping", "sql-db"),
                         ("Illuminate\\Database\\Eloquent\\Model", "sql-db"), ("Illuminate\\Support\\Facades\\DB", "sql-db"),
                         ("PhpAmqpLib\\Connection", "event"), ("Enqueue\\SimpleClient", "event"),
                         ("Predis\\Client", "cache"), ("Redis", "cache"), ("GuzzleHttp\\Client", "http-out"),
                         ("Illuminate\\Support\\Facades\\Route", "http-in"), ("Illuminate\\Support\\Facades\\Http", "http-out"),
                         ("Symfony\\Component\\Routing\\Attribute\\Route", "http-in"),
                         ("Symfony\\Contracts\\HttpClient\\HttpClientInterface", "http-out")):
        assert [h["kind"] for h in stack.sink_kinds(st, "php", target)] == [kind], target
    for target in ("Illuminate\\Http\\Request", "Illuminate\\Support\\Collection",
                   "Symfony\\Component\\HttpFoundation\\Response", "Symfony\\Bundle\\FrameworkBundle\\Controller"):
        assert stack.covered(st, "php", target) and stack.sink_kinds(st, "php", target) == [], target


# every pack

@pytest.mark.parametrize("lang", ["go", "csharp", "rust", "ruby", "php"])
def test_every_pack_regex_entry_has_when(lang):
    """A pack regex without `when` fires on any file of the language. The exceptions are files
    that import nothing, each with a tight regex and look-alike tests: Rails routes and resources, C#
    minimal APIs (implicit usings), Laravel routes (the global `Route` alias), Rails models (`self.table_name`)
    and gorm models (`TableName`)."""
    st = stack.default()
    no_when = {("ruby", "rails"), ("ruby", "rails-resources"), ("ruby", "rails-resource"),
               ("ruby", "active-record-table-name"), ("csharp", "aspnet-minimal"),
               ("csharp", "aspnet-map-group"), ("php", "laravel"), ("php", "laravel-match"), ("php", "laravel-prefix"),
               ("go", "gorm-table-name")}
    for p in (*st.patterns, *st.tables):
        if p.lang == lang and p.source == "pack":
            assert bool(p.when) != ((lang, p.name) in no_when), p.name


def test_stack_yaml_replaces_a_new_pack_entry(make_repo):
    repo = make_repo(SINATRA_SERVICE)
    with_stack(repo, "ruby:\n  routes:\n    - {name: sinatra, when: sinatra, path: literal, method: GET,\n"
                     "       regex: '^get \"(?P<path>/orders[^\"]*)\" do'}\n")
    s = structure.build(repo, "docs/viz-code")
    assert [(r["method"], r["path"]) for r in s["facts"]["app.rb"]["routes"]] == [("GET", "/orders/{id}")]
    assert {"lang": "ruby", "group": "routes", "name": "sinatra"} in s["stack"]["overrides"]


def test_csharp_global_usings_reach_every_file_of_their_project(make_repo):
    """`global using` in any file of a project, and `<Using Include>` in its .csproj, import the namespace in every
    file of that project, so a pack's `when` holds there; another project does not get them."""
    s = build(make_repo, {
        "Data/Data.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\">\n  <ItemGroup>\n"
                            "    <Using Include=\"System.ComponentModel.DataAnnotations.Schema\" />\n"
                            "  </ItemGroup>\n</Project>\n",
        "Data/GlobalUsings.cs": "global using Microsoft.EntityFrameworkCore;\n",
        "Data/OrderConfig.cs": "namespace Data;\n\nclass OrderConfig {\n"
                               "  public void Configure(EntityTypeBuilder<Order> b) { b.ToTable(\"orders\"); }\n}\n",
        "Data/Line.cs": "namespace Data;\n\n[Table(\"order_lines\")]\npublic class Line { public int Id { get; set; } }\n",
        "Other/Other.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
        "Other/Config.cs": "namespace Other;\n\nclass C {\n  void M(B b) { b.ToTable(\"audit\"); }\n}\n"})
    assert [t["table"] for t in s["facts"]["Data/OrderConfig.cs"]["tables"]] == ["orders"]
    assert [t["table"] for t in s["facts"]["Data/Line.cs"]["tables"]] == ["order_lines"]
    assert "tables" not in s["facts"]["Other/Config.cs"]
