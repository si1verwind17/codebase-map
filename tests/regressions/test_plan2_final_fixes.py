"""Final-review fixes of the language packs: stacked attribute groups, client interfaces, Axum chained method
routers, EF Core migrations, inline handlers, framework wiring, the default path reader, small table fixes."""
from vizcode.scan import stack, structure

from helpers import routes


def build(make_repo, files, name="demo"):
    return structure.build(make_repo(files, name=name), "docs/viz-code")


# --- 1. stacked attribute groups ---------------------------------------------------------------------------

def test_php_stacked_attribute_groups(make_repo):
    ctrl = ("<?php\n\nnamespace App\\Controller\\Admin;\n\n"
            "use Symfony\\Component\\Routing\\Attribute\\Route;\nuse Symfony\\Component\\Security\\Http\\Attribute\\IsGranted;\n\n"
            "#[Route('/admin/post')]\n#[IsGranted('ROLE_ADMIN')]\nfinal class BlogController\n{\n"
            "    #[Route('/', name: 'admin_index', methods: ['GET'])]\n"
            "    #[Route('/', name: 'admin_post_index', methods: ['GET'])]\n    public function index() {}\n\n"
            "    #[Route('/new', name: 'admin_post_new', methods: ['GET', 'POST'])]\n"
            "    #[IsGranted('ROLE_EDITOR')]\n    public function new() {}\n\n"
            "    #[Route('/{id}/edit', methods: ['POST'])] #[IsGranted('edit', subject: 'post')]\n"
            "    public function edit() {}\n}\n")
    s = build(make_repo, {"composer.json": "{}\n", "src/Controller/Admin/BlogController.php": ctrl})
    c = ".::App\\Controller\\Admin.BlogController"
    assert routes(s, "src/Controller/Admin/BlogController.php") == [
        ("GET", "/admin/post", f"{c}#index/0", 12, "symfony", "pack"),
        ("GET", "/admin/post/new", f"{c}#new/0", 16, "symfony", "pack"),
        ("POST", "/admin/post/new", f"{c}#new/0", 16, "symfony", "pack"),
        ("POST", "/admin/post/{id}/edit", f"{c}#edit/0", 20, "symfony", "pack")]


def test_parse_annotations_splits_groups():
    assert [a[0] for a in stack.parse_annotations("#[Route('/a')]\n  // why\n#[IsGranted('x'), Cache]")] == \
        ["Route", "IsGranted", "Cache"]
    assert [a[0] for a in stack.parse_annotations("[Route(\"a\")] [HttpGet]")] == ["Route", "HttpGet"]
    assert stack.parse_annotations("#[Route('/a')] junk") == []
    assert stack.parse_annotations("#[Route('/a')]\n#[") == []


# --- 2. client interfaces are not servers ------------------------------------------------------------------

JAVA_CLIENTS = {
    "pom.xml": "<project><artifactId>shop</artifactId></project>\n",
    "src/main/java/shop/StockClient.java":
        "package shop;\n\nimport org.springframework.cloud.openfeign.FeignClient;\n"
        "import org.springframework.web.bind.annotation.*;\n\n"
        "@FeignClient(name = \"stock\")\npublic interface StockClient {\n"
        "    @GetMapping(\"/stock/{sku}\")\n    Stock get(@PathVariable String sku);\n}\n",
    "src/main/java/shop/PriceClient.java":
        "package shop;\n\nimport org.springframework.web.service.annotation.HttpExchange;\n"
        "import org.springframework.web.bind.annotation.*;\n\n"
        "@HttpExchange(\"/prices\")\n@RequestMapping(\"/prices\")\npublic interface PriceClient {\n"
        "    @PostMapping(\"/{sku}\")\n    void set(String sku);\n}\n",
    "src/main/java/shop/TaxClient.java":
        "package shop;\n\nimport jakarta.ws.rs.*;\nimport org.eclipse.microprofile.rest.client.inject.RegisterRestClient;\n\n"
        "@Path(\"/tax\")\n@RegisterRestClient(configKey = \"tax\")\npublic interface TaxClient {\n"
        "    @GET\n    @Path(\"/{sku}\")\n    Tax get(@PathParam(\"sku\") String sku);\n}\n",
    "src/main/java/shop/ShipClient.java":
        "package shop;\n\nimport io.micronaut.http.annotation.*;\nimport io.micronaut.http.client.annotation.Client;\n\n"
        "@Client(\"/ship\")\npublic interface ShipClient {\n    @Get(\"/{id}\")\n    Ship get(String id);\n}\n",
    "src/main/java/shop/OrderController.java":
        "package shop;\n\nimport org.springframework.web.bind.annotation.*;\n\n"
        "@RestController\n@RequestMapping(\"/orders\")\npublic class OrderController {\n"
        "    @GetMapping(\"/{id}\")\n    public Order get(@PathVariable String id) { return null; }\n}\n",
}


def test_client_interfaces_give_no_routes(make_repo):
    s = build(make_repo, JAVA_CLIENTS)
    every = {f: routes(s, f) for f in s["facts"] if routes(s, f)}
    assert every == {"src/main/java/shop/OrderController.java": [
        ("GET", "/orders/{id}", ".::shop.OrderController#get/1", 8, "spring-web", "pack")]}


def test_client_interfaces_give_no_routes_in_kotlin(make_repo):
    s = build(make_repo, {"settings.gradle.kts": "rootProject.name = \"shop\"\n", "src/main/kotlin/shop/Clients.kt":
                          "package shop\n\nimport org.springframework.cloud.openfeign.FeignClient\n"
                          "import org.springframework.web.bind.annotation.GetMapping\n\n"
                          "@FeignClient(name = \"stock\")\ninterface StockClient {\n"
                          "    @GetMapping(\"/stock\")\n    fun all(): List<Stock>\n}\n"})
    assert routes(s, "src/main/kotlin/shop/Clients.kt") == []


def test_skip_class_validation(tmp_path):
    import pytest
    from test_stack import write
    bad = write(tmp_path, "java:\n  routes:\n    - {name: x, form: annotated, verbs: {Get: GET}, skip_class: Client}\n")
    with pytest.raises(stack.StackError, match="skip_class must be a list of annotation names"):
        stack.load(bad)


# --- 3. Axum chained method routers ------------------------------------------------------------------------

def found(lang, src, imports):
    return [(r["method"], r["path"], r.get("handler_name"), r["framework"])
            for r in stack.find_routes(stack.default(), lang, src, imports, [], "f")]


def test_axum_chained_method_router():
    src = ('Router::new()\n  .route("/a", get(list).post(create))\n'
           '  .route(\n    "/a/:id",\n    get(show)\n      .put(articles::update)\n      .delete(drop)\n      .patch(fix),\n  )\n'
           '  .route("/b", any(h).get(g))\n  .route("/c", get(|| async {}).post(p))\n  .route("/d", get(d).layer(x))\n')
    got = found("rust", src, ["axum::Router"])
    assert sorted(got) == sorted([
        ("GET", "/a", "list", "axum"), ("POST", "/a", "create", "axum-chain-2"),
        ("GET", "/a/{id}", "show", "axum"), ("PUT", "/a/{id}", "articles::update", "axum-chain-2"),
        ("DELETE", "/a/{id}", "drop", "axum-chain-3"), ("PATCH", "/a/{id}", "fix", "axum-chain-4"),
        ("ANY", "/b", "h", "axum"), ("GET", "/b", "g", "axum-chain-2"),
        ("GET", "/c", None, "axum"), ("GET", "/d", "d", "axum")])
    assert found("rust", src, ["serde"]) == []


def test_axum_chained_handlers_resolve(make_repo):
    s = build(make_repo, {"Cargo.toml": "[package]\nname = \"a\"\n", "src/main.rs":
                          "use axum::{routing::get, Router};\n\nfn app() -> Router {\n"
                          "    Router::new().route(\"/x\", get(a).put(b))\n}\n\nasync fn a() {}\nasync fn b() {}\n"})
    assert routes(s, "src/main.rs") == [("GET", "/x", ".::src/main.rs#a/0", 4, "axum", "pack"),
                                        ("PUT", "/x", ".::src/main.rs#b/0", 4, "axum-chain-2", "pack")]


# --- 4. EF Core migrations ---------------------------------------------------------------------------------

def test_ef_core_generated_migrations_are_excluded(make_repo):
    s = build(make_repo, {
        "Shop.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
        "Data/Migrations/20200101_Init.cs": "namespace Shop.Migrations;\npublic partial class Init {}\n",
        "Data/Migrations/20200101_Init.Designer.cs":
            "using Microsoft.EntityFrameworkCore;\nnamespace Shop.Migrations;\npublic partial class Init {\n"
            "    void B(dynamic b) { b.ToTable(\"Orders\"); }\n}\n",
        "Data/Migrations/ShopContextModelSnapshot.cs":
            "using Microsoft.EntityFrameworkCore;\nnamespace Shop.Migrations;\nclass ShopContextModelSnapshot {\n"
            "    void B(dynamic b) { b.ToTable(\"Orders\"); }\n}\n",
        "Migrations/ShopContextModelSnapshot.cs": "namespace Shop.Migrations;\nclass S {}\n",
        "Data/OrderConfig.Designer.cs": "namespace Shop.Data;\nclass OrderConfig {}\n",
        "app/Migrations/x.Designer.py": "X = 1\n"})
    assert {"Data/Migrations/20200101_Init.Designer.cs", "Data/Migrations/ShopContextModelSnapshot.cs",
            "Migrations/ShopContextModelSnapshot.cs"} <= set(s["excluded"])
    assert {"Data/Migrations/20200101_Init.cs", "Data/OrderConfig.Designer.cs"} <= set(s["files"])


# --- 5. an inline handler is the file -----------------------------------------------------------------------

def test_an_inline_handler_at_the_file_top_is_a_method_of_the_file(make_repo):
    s = build(make_repo, {
        "package.json": "{\"name\": \"api\"}\n",
        # a class but no top-level function: the handler is the file, not the class
        "src/tags.ts": "import { Router } from 'express';\nconst router = Router();\n"
                       "export class TagCache { get() { return 1; } }\n"
                       "router.get('/tags', async (req, res) => { res.json([]); });\nexport default router;\n",
        # no function node at all
        "src/ping.ts": "import { Router } from 'express';\nconst router = Router();\n"
                       "router.get('/ping', (req, res) => res.send('ok'));\nexport default router;\n",
        # a named handler resolves: no file node is made
        "src/users.ts": "import { Router } from 'express';\nimport { list } from './handlers';\n"
                        "const router = Router();\nrouter.get('/users', list);\nexport default router;\n",
        "src/handlers.ts": "export function list(req, res) { res.json([]); }\n"})
    assert routes(s, "src/tags.ts") == [("GET", "/tags", ".::src/tags.ts#get_tags/0", 4, "express", "pack")]
    assert routes(s, "src/ping.ts") == [("GET", "/ping", ".::src/ping.ts#get_ping/0", 3, "express", "pack")]
    assert routes(s, "src/users.ts") == [("GET", "/users", ".::src/handlers.ts#list/2", 4, "express", "pack")]
    files = {n["id"]: n for n in s["nodes"] if n["kind"] == "file"}
    assert {".::src/tags.ts", ".::src/ping.ts", ".::src/handlers.ts"} <= set(files)
    assert ".::src/users.ts" not in files
    assert files[".::src/ping.ts"] == {"id": ".::src/ping.ts", "kind": "file", "parent": ".::src/", "name": "ping.ts",
                                       "lang": "typescript", "file": "src/ping.ts", "line": 1, "visibility": "public",
                                       "metrics": {"loc": 5, "methods": 1}}


# --- 6. framework wiring ----------------------------------------------------------------------------------

def test_ktor_and_jakarta_wiring_kinds():
    st = stack.default()
    for lang, target, kind in (
            ("kotlin", "io.ktor.client.HttpClient", "http-out"), ("kotlin", "io.ktor.client.request.get", "http-out"),
            ("kotlin", "io.ktor.server.routing.get", "http-in"), ("kotlin", "io.ktor.server.websocket.webSocket", "ws"),
            ("java", "jakarta.persistence.Entity", "sql-db"), ("java", "jakarta.ws.rs.GET", "http-in"),
            ("java", "jakarta.ws.rs.core.Response", "http-in"), ("java", "jakarta.ws.rs.client.Client", "http-out"),
            ("java", "jakarta.jms.Message", "event"), ("java", "javax.jms.Message", "event"),
            ("kotlin", "jakarta.persistence.Entity", "sql-db"), ("kotlin", "jakarta.jms.Message", "event"),
            ("java", "org.eclipse.microprofile.rest.client.inject.RegisterRestClient", "http-out"),
            ("java", "org.eclipse.microprofile.reactive.messaging.Incoming", "event")):
        assert [h["kind"] for h in stack.sink_kinds(st, lang, target)] == [kind], (lang, target)
    for lang, target in (("kotlin", "io.ktor.server.application.Application"), ("kotlin", "io.ktor.http.HttpStatusCode"),
                         ("kotlin", "io.ktor.server.plugins.contentnegotiation.ContentNegotiation"),
                         ("kotlin", "io.ktor.serialization.kotlinx.json.json"),
                         ("java", "jakarta.inject.Inject"), ("java", "jakarta.enterprise.context.ApplicationScoped"),
                         ("java", "jakarta.validation.constraints.NotNull"), ("java", "jakarta.annotation.PostConstruct"),
                         ("java", "jakarta.transaction.Transactional"), ("kotlin", "jakarta.validation.Valid"),
                         ("java", "org.eclipse.microprofile.config.inject.ConfigProperty")):
        assert stack.covered(st, lang, target) and stack.sink_kinds(st, lang, target) == [], (lang, target)


def test_wiring_is_not_listed(make_repo):
    s = build(make_repo, {
        "settings.gradle.kts": "rootProject.name = \"shop\"\n",
        "src/main/kotlin/shop/App.kt":
            "package shop\n\nimport io.ktor.server.application.*\nimport io.ktor.server.plugins.cors.routing.CORS\n"
            "import io.ktor.server.routing.*\nimport io.ktor.http.HttpStatusCode\nimport jakarta.inject.Inject\n\n"
            "fun Application.module() {\n    routing {\n        get(\"/x\") {\n        }\n    }\n}\n",
        "src/main/java/shop/Res.java":
            "package shop;\n\nimport jakarta.enterprise.context.ApplicationScoped;\nimport jakarta.validation.Valid;\n"
            "import jakarta.ws.rs.*;\nimport jakarta.ws.rs.core.Response;\n\n@Path(\"/r\")\n@ApplicationScoped\n"
            "public class Res {\n    @GET\n    public Response get() { return null; }\n}\n"})
    assert s["stack"]["unrecognised"] == []
    assert routes(s, "src/main/kotlin/shop/App.kt")[0][:2] == ("GET", "/x")
    assert routes(s, "src/main/java/shop/Res.java")[0][:2] == ("GET", "/r")


# --- 7. the path reader defaults to literal ------------------------------------------------------------------

def test_path_reader_defaults_to_literal(tmp_path):
    import pytest
    from test_stack import write
    st = stack.load(write(tmp_path, "go:\n  routes:\n"
                                    "    - {name: r, method: GET, regex: 'R\\(\"(?P<path>[^\"]*)\"\\)'}\n"
                                    "    - {name: m, mount: true, regex: 'M\\(\"(?P<path>[^\"]*)\"\\)'}\n"))
    mine = {p.name: p for p in st.patterns if p.source == "stack.yaml"}
    assert mine["r"].path == "literal" and mine["m"].path == "literal"
    src = 'R("/a/:id")\nM("/v1/")\n'
    assert [(r["method"], r["path"]) for r in stack.find_routes(st, "go", src, [], [], "f")
            if r["framework"] == "r"] == [("GET", "/a/{id}")]
    assert [m["path"] for m in stack.find_mounts(st, "go", src, []) if m["framework"] == "m"] == ["/v1"]
    for bad in ("path: words", "path: ''", "path: [literal]"):
        with pytest.raises(stack.StackError, match="unknown path reader"):
            stack.load(write(tmp_path, f"go:\n  routes:\n    - {{name: r, method: GET, {bad}, regex: '(?P<path>x)'}}\n"))


# --- 9. small table fixes ----------------------------------------------------------------------------------

def test_exposed_table_without_a_name():
    src = ("object Users : Table() {\n}\nobject OrdersTable : IntIdTable()\nobject Items : Table(\"item_rows\")\n"
           "class Tags : org.jetbrains.exposed.sql.Table( )\nobject Other : Something()\n")
    got = [(t["table"], t["pattern"]) for t in stack.find_tables(stack.default(), "kotlin", src,
                                                                 ["org.jetbrains.exposed.sql.Table"], [], [], "f")]
    assert sorted(got) == sorted([("Users", "exposed-unnamed"), ("Orders", "exposed-unnamed"),
                                  ("item_rows", "exposed"), ("Tags", "exposed-unnamed")])
    assert stack.find_tables(stack.default(), "kotlin", src, ["org.jetbrains.exposed.dao"], [], [], "f") != []
    assert stack.find_tables(stack.default(), "kotlin", src, ["kotlin.collections"], [], [], "f") == []


def test_jpa_entity_name_gives_way_to_table_name(make_repo):
    from test_packs_jvm import tables
    s = build(make_repo, {
        "pom.xml": "<project><artifactId>shop</artifactId></project>\n",
        "src/main/java/shop/Order.java":
            "package shop;\n\nimport jakarta.persistence.*;\n\n@Entity(name = \"Order\")\n@Table(name = \"orders\")\n"
            "public class Order {\n}\n",
        "src/main/java/shop/Item.java":
            "package shop;\n\nimport jakarta.persistence.*;\n\n@Table(name = \"items\")\n@Entity(name = \"Item\")\n"
            "public class Item {\n}\n",
        "src/main/java/shop/Tag.java":
            "package shop;\n\nimport jakarta.persistence.*;\n\n@Entity(name = \"tags\")\npublic class Tag {\n}\n"})
    assert tables(s, "src/main/java/shop/Order.java") == [("orders", 6, ".::shop.Order", "defined", "jpa-table-name")]
    assert tables(s, "src/main/java/shop/Item.java") == [("items", 5, ".::shop.Item", "defined", "jpa-table-name")]
    assert tables(s, "src/main/java/shop/Tag.java") == [("tags", 5, ".::shop.Tag", "defined", "jpa-entity-name")]
