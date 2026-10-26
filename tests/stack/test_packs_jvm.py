"""The Java and Kotlin built-in packs (imports, annotated and regex routes, ORM tables), the Scala and Python
table patterns, and the Spring Boot and Ktor fixtures mapped with packs only (no stack.yaml)."""
import pytest

from vizcode.scan import stack, structure

from helpers import routes, sinks, tables, write

API = "api/src/main/java/io/demo/shop/api"
CTRL = "api::io.demo.shop.api.OrderController"
LEGACY = "legacy/src/main/java/io/demo/shop/legacy"
APP = "src/main/kotlin/io/demo/orders/Application.kt"


def build(make_repo, files, name="demo"):
    return structure.build(make_repo(files, name=name), "docs/viz-code")


# Spring Boot (Maven multi-module) with packs only

def test_spring_routes(spring_repo):
    s = structure.build(spring_repo, "docs/viz-code")
    assert routes(s, f"{API}/OrderController.java") == [
        ("GET", "/v1/orders/{id}", f"{CTRL}#get/1", 14, "spring-web", "pack"),
        ("POST", "/v1/orders", f"{CTRL}#create/1", 17, "spring-web", "pack"),
        ("DELETE", "/v1/orders/{id}", f"{CTRL}#delete/1", 20, "spring-web", "pack")]
    for f in ("PricingClient.java", "OrderEvents.java"):
        assert routes(s, f"{API}/{f}") == []


def test_spring_sinks_and_tables(spring_repo):
    s = structure.build(spring_repo, "docs/viz-code")
    assert sinks(s, f"{API}/PricingClient.java") == [("http-out", "org.springframework.web.client")]
    assert sinks(s, f"{API}/OrderEvents.java") == [("event", "org.springframework.kafka")]
    assert sinks(s, f"{API}/OrderController.java") == [("http-in", "org.springframework.web.bind.annotation")]
    common = "common/src/main/java/io/demo/shop/common"
    assert sinks(s, f"{common}/OrderRepository.java") == [("sql-db", "org.springframework.data.jpa")]
    assert sinks(s, f"{common}/Order.java") == [("sql-db", "jakarta.persistence")] * 3
    assert tables(s, f"{common}/Order.java") == [
        ("orders", 8, "common::io.demo.shop.common.Order", "defined", "jpa-table-name")]
    assert "mounts" not in s["facts"][f"{API}/OrderController.java"]


def test_spring_beside_jaxrs(spring_repo):
    """Both frameworks count in the pattern report; a method both annotate is one route."""
    s = structure.build(spring_repo, "docs/viz-code")
    stock = "legacy::io.demo.shop.legacy.StockResource"
    assert routes(s, f"{LEGACY}/StockResource.java") == [
        ("GET", "/legacy/stock", f"{stock}#list/0", 7, "jaxrs", "pack"),
        ("GET", "/legacy/stock/{sku}", f"{stock}#one/1", 10, "jaxrs", "pack")]
    assert routes(s, f"{LEGACY}/BothResource.java") == [
        ("GET", "/legacy/both", "legacy::io.demo.shop.legacy.BothResource#list/0", 12, "spring-web", "pack")]
    pats = {(p["lang"], p["name"]): (p["matches"], p["files"], p["source"], p.get("form"))
            for p in s["stack"]["patterns"]}
    assert pats[("java", "spring-web")] == (4, 2, "pack", "annotated")
    assert pats[("java", "jaxrs")] == (2, 1, "pack", "annotated")
    assert ("java", "jaxrs-javax") not in pats and ("java", "micronaut") not in pats
    md = structure.summary_md(s)
    assert "- java spring-web (pack): 4 routes in 2 files\n" in md
    assert "- java jaxrs (pack): 2 routes in 1 file\n" in md


def test_dedupe_keeps_the_first_pattern(make_repo):
    """Two patterns giving the same (method, path, handler) give one route, named after the first pattern;
    one pattern's own matches are never merged."""
    files = {"pom.xml": "<project/>\n",
             "src/main/java/a/R.java": "package a;\n\nimport jakarta.ws.rs.*;\n\n@Path(\"/r\")\npublic class R {\n"
                                       "  @GET @HEAD\n  public String x() { return \"\"; }\n}\n"}
    repo = make_repo(files)
    from conftest import with_stack
    with_stack(repo, "java:\n  routes:\n    - name: again\n      form: annotated\n      when: jakarta.ws.rs\n"
                     "      prefix: [Path]\n      verbs: {GET: GET}\n")
    s = structure.build(repo, "docs/viz-code")
    got = [(r["method"], r["path"], r["framework"]) for r in s["facts"]["src/main/java/a/R.java"]["routes"]]
    assert got == [("GET", "/r", "jaxrs"), ("HEAD", "/r", "jaxrs")]


def test_micronaut_and_javax_jaxrs(make_repo):
    s = build(make_repo, {
        "pom.xml": "<project/>\n",
        "src/main/java/a/M.java": "package a;\n\nimport io.micronaut.http.annotation.*;\n\n"
                                  "@Controller(\"/m\")\npublic class M {\n  @Get(\"/{id}\")\n  public String one(String id) "
                                  "{ return id; }\n  @Post(uri = \"/new\")\n  public void make() {}\n}\n",
        "src/main/java/a/J.java": "package a;\n\nimport javax.ws.rs.*;\n\n@Path(\"j\")\npublic class J {\n"
                                  "  @DELETE @Path(\"/{id}\")\n  public void drop(String id) {}\n}\n"})
    assert [(r["method"], r["path"], r["framework"]) for r in s["facts"]["src/main/java/a/M.java"]["routes"]] == [
        ("GET", "/m/{id}", "micronaut"), ("POST", "/m/new", "micronaut")]
    assert [(r["method"], r["path"], r["framework"]) for r in s["facts"]["src/main/java/a/J.java"]["routes"]] == [
        ("DELETE", "/j/{id}", "jaxrs-javax")]


def test_java_imports_win_over_ignore():
    st = stack.default()
    assert stack.sink_kinds(st, "java", "java.net.http.HttpClient") == [{"kind": "http-out", "lib": "java.net.http"}]
    assert stack.sink_kinds(st, "java", "java.sql.Connection") == [{"kind": "sql-db", "lib": "java.sql"}]
    assert stack.sink_kinds(st, "java", "java.util.List") == [] and stack.covered(st, "java", "java.util.List")
    for target, kind in (("org.jooq.DSLContext", "sql-db"), ("com.mongodb.client", "doc-db"),
                         ("org.apache.kafka.clients.producer", "event"), ("redis.clients.jedis", "cache"),
                         ("okhttp3.OkHttpClient", "http-out"), ("software.amazon.awssdk.services.s3", "cloud-sdk"),
                         ("io.grpc.ManagedChannel", "grpc"),
                         ("org.springframework.web.reactive.function.client.WebClient", "http-out")):
        assert [h["kind"] for h in stack.sink_kinds(st, "java", target)] == [kind], target
    for target, kind in (("org.jetbrains.exposed.sql", "sql-db"), ("io.ktor.client.HttpClient", "http-out"),
                         ("io.ktor.server.routing", "http-in"), ("java.net.http", "http-out")):
        assert [h["kind"] for h in stack.sink_kinds(st, "kotlin", target)] == [kind], target


def test_jpa_table_shapes(make_repo):
    src = ("package a;\n\nimport javax.persistence.*;\n\n"
           "@Entity(name = \"Ord\")\n@Table(schema = \"s\", name = \"orders\")\nclass A {}\n\n"
           "@Table(indexes = {@Index(name = \"idx\", columnList = \"x\")})\nclass B {}\n")
    s = build(make_repo, {"pom.xml": "<project/>\n", "src/main/java/a/A.java": src})
    # the entity name gives way to the table name on the same class
    assert [(t["table"], t["in"], t["kind"], t["pattern"]) for t in s["facts"]["src/main/java/a/A.java"]["tables"]] == [
        ("orders", ".::a.A", "defined", "jpa-table-name-javax")]


def test_jpa_needs_its_import(make_repo):
    s = build(make_repo, {"pom.xml": "<project/>\n",
                          "src/main/java/a/A.java": "package a;\n\n@Table(name = \"orders\")\nclass A {}\n"})
    assert not s["facts"]["src/main/java/a/A.java"].get("tables")


# Ktor (Gradle) with packs only

def test_ktor_routes_mounts_tables(ktor_repo):
    s = structure.build(ktor_repo, "docs/viz-code")
    # each inline handler block is a node of its own, named after its route
    module = ".::io.demo.orders/Application.kt#module"
    assert routes(s, APP) == [
        ("GET", "/v1/orders/{id}", f"{module}.get_v1_orders_id/0", 12, "ktor", "pack"),
        ("POST", "/v1/orders", f"{module}.post_v1_orders/0", 15, "ktor", "pack"),
        ("GET", "/health", f"{module}.get_health/0", 19, "ktor", "pack")]
    assert [(m["path"], m["line"], m["framework"]) for m in s["facts"][APP]["mounts"]] == [("/v1", 11, "ktor-route")]
    orders = "src/main/kotlin/io/demo/orders/Orders.kt"
    assert tables(s, orders) == [("orders", 7, ".::io.demo.orders.Orders", "defined", "exposed"),
                                 ("orders", 12, ".::io.demo.orders.OrderRepo#find/1", "access", "orm-call")]
    assert sinks(s, orders) == [("sql-db", "org.jetbrains.exposed")] * 3
    assert sorted(set(sinks(s, APP))) == [("http-in", "io.ktor.server.routing"), ("http-out", "io.ktor.client")]
    assert s["stack"]["unrecognised"] == []
    md = structure.summary_md(s)
    assert "- **mounts:** /v1 (src/main/kotlin/io/demo/orders/Application.kt:11, composed onto 2 routes)\n" in md
    assert "- **tables (patterns):** orders (src/main/kotlin/io/demo/orders/Orders.kt:7 defined on" in md


def test_ktor_regex_negatives(make_repo):
    """Ktor's route and mount patterns fire only under `io.ktor.server.routing`, and never on a
    member call (`client.get("/x") { }`, `m.get("/x")`) or a string template path."""
    src = ("package a\n\nfun f(client: Any, m: Map<String, Int>) {\n    client.get(\"/remote\") { }\n"
           "    m.get(\"/k\")\n    get(\"/x\") { }\n    route(\"/v2\") { }\n}\n")
    s = build(make_repo, {"settings.gradle.kts": "", "src/main/kotlin/a/F.kt": src})
    f = s["facts"]["src/main/kotlin/a/F.kt"]
    assert not f.get("routes") and not f.get("mounts")
    s = build(make_repo, {"settings.gradle.kts": "", "src/main/kotlin/a/F.kt":
                          src.replace("package a\n", "package a\n\nimport io.ktor.server.routing.*\n")
                          + "fun g() { get(\"/t/$id\") { } }\n"}, name="b")
    f = s["facts"]["src/main/kotlin/a/F.kt"]
    assert [(r["method"], r["path"]) for r in f["routes"]] == [("GET", "/x")]
    assert [m["path"] for m in f["mounts"]] == ["/v2"]


def test_kotlin_spring_and_jpa(make_repo):
    src = ("package a\n\nimport jakarta.persistence.*\nimport org.springframework.web.bind.annotation.*\n\n"
           "@Entity\n@Table(name = \"orders\")\nclass Order(@Id val id: Long)\n\n"
           "@RestController\n@RequestMapping(\"/k\")\nclass K {\n"
           "    @GetMapping(\"/{id}\")\n    fun one(@PathVariable id: Long) = id\n"
           "    @RequestMapping(value = [\"/x\"], method = [RequestMethod.PUT])\n    fun put() {}\n}\n")
    s = build(make_repo, {"settings.gradle.kts": "", "src/main/kotlin/a/K.kt": src})
    f = s["facts"]["src/main/kotlin/a/K.kt"]
    assert [(r["method"], r["path"], r["framework"]) for r in f["routes"]] == [
        ("GET", "/k/{id}", "spring-web"), ("PUT", "/k/x", "spring-web")]
    assert [(t["table"], t["in"], t["pattern"]) for t in f["tables"]] == [("orders", ".::a.Order", "jpa-table-name")]


def test_exposed_negative(make_repo):
    src = "package a\n\nobject Orders : Table(\"orders\")\n"
    s = build(make_repo, {"settings.gradle.kts": "", "src/main/kotlin/a/T.kt": src})
    assert not s["facts"]["src/main/kotlin/a/T.kt"].get("tables")
    s = build(make_repo, {"settings.gradle.kts": "", "src/main/kotlin/a/T.kt":
                          src.replace("\n\n", "\n\nimport org.jetbrains.exposed.dao.id.IntIdTable\n\n", 1)
                          .replace("Table(", "IntIdTable(") + "val t = Table(\"x\")\n"}, name="b")
    assert [t["table"] for t in s["facts"]["src/main/kotlin/a/T.kt"]["tables"]] == ["orders"]


# Scala and Python table patterns

def test_quill_query_type_as_written():
    st = stack.default()
    src = ("object R {\n  def a = run(query[OrderTransaction].filter(_.id == 1))\n"
           "  def b = endpoint.in(query[String](\"zone\"))\n  def c = query[model.Order]\n  def d = myquery[X]\n}\n")
    got = stack.find_tables(st, "scala", src, ["io.getquill"], [(2, 2, "a"), (3, 3, "b"), (4, 4, "c"), (5, 5, "d")],
                            [(1, 6, "R")], "f")
    assert [(t["table"], t["in"], t["kind"], t["pattern"], t["source"]) for t in got] == [
        ("OrderTransaction", "a", "access", "quill", "pack"), ("model.Order", "c", "access", "quill", "pack")]
    assert stack.find_tables(st, "scala", src, ["sttp.tapir"], [], [], "f") == []


def test_python_tables():
    st = stack.default()
    sqla = "class Order(Base):\n    __tablename__ = \"orders\"\n"
    got = stack.find_tables(st, "python", sqla, ["sqlalchemy.orm"], [], [(1, 2, "Order")], "f")
    assert [(t["table"], t["in"], t["kind"], t["pattern"]) for t in got] == [("orders", "Order", "defined", "sqlalchemy")]
    assert stack.find_tables(st, "python", sqla, [], [], [(1, 2, "Order")], "f") == []
    dj = "class Order(models.Model):\n    class Meta:\n        db_table = 'shop_orders'\n"
    got = stack.find_tables(st, "python", dj, ["django.db.models"], [], [(1, 3, "Order"), (2, 3, "Order.Meta")], "f")
    assert [(t["table"], t["in"], t["pattern"]) for t in got] == [("shop_orders", "Order.Meta", "django")]
    assert stack.find_tables(st, "python", dj, ["flask"], [], [], "f") == []


@pytest.mark.parametrize("lang", ["java", "kotlin"])
def test_every_pack_regex_route_has_when(lang):
    """A pack regex route without `when` would fire on any file of the language."""
    for p in stack.default().patterns:
        if p.lang == lang and p.source == "pack":
            assert p.when, p.name


def test_pack_names_do_not_block_a_stack_yaml(tmp_path):
    """A stack.yaml written before the packs (the old example names) still loads."""
    st = stack.load(write(tmp_path, "java:\n  routes:\n    - name: spring-mvc\n      form: annotated\n"
                                    "      verbs: {GetMapping: GET}\n  tables:\n    - {name: jpa-table, regex: '(?P<table>x)'}\n"))
    assert {p.name for p in st.patterns if p.lang == "java"} >= {"spring-mvc", "spring-web"}


def test_table_dedupe_across_patterns(make_repo):
    """A stack.yaml table pattern that repeats a pack's gives one fact per (table, line, in), named after the
    pack's pattern; a different table on the same line stays."""
    from conftest import with_stack
    repo = make_repo({"build.sbt": "", "R.scala": "import io.getquill.*\n\nobject R {\n"
                                                   "  def a = run(query[Order].join(query[Item]))\n}\n"})
    with_stack(repo, "scala:\n  tables:\n    - {name: mine, when: io.getquill, regex: 'query\\[(?P<table>Order)\\]'}\n")
    s = structure.build(repo, "docs/viz-code")
    assert [(t["table"], t["line"], t["pattern"]) for t in s["facts"]["R.scala"]["tables"]] == [
        ("Order", 4, "quill"), ("Item", 4, "quill")]


# stack.yaml replaces a pack entry by name; framework wiring ignored by its pack;
# a stack.yaml pattern a pack pattern duplicates is reported as such; pack gaps; dedupe order per group

def test_stack_yaml_entry_replaces_the_pack_entry_of_that_name(make_repo):
    from conftest import with_stack
    repo = make_repo({"build.sbt": "", "R.scala": "import io.getquill.*\n\nobject R {\n"
                                                   "  def a = run(query[Order])\n  def b = run(myQuery[Item])\n}\n"})
    with_stack(repo, "scala:\n  tables:\n    - {name: quill, when: io.getquill, regex: 'uery\\[(?P<table>\\w+)\\]'}\n")
    s = structure.build(repo, "docs/viz-code")
    assert [(t["table"], t["pattern"], t["source"]) for t in s["facts"]["R.scala"]["tables"]] == [
        ("Order", "quill", "stack.yaml"), ("Item", "quill", "stack.yaml")]
    assert {"lang": "scala", "group": "tables", "name": "quill"} in s["stack"]["overrides"]
    pats = [p for p in s["stack"]["patterns"] if p["name"] == "quill"]
    assert [(p["source"], p["matches"]) for p in pats] == [("stack.yaml", 2)]
    md = structure.summary_md(s)
    assert "Pack entries replaced by stack.yaml (1):\n- scala table quill: stack.yaml replaces the pack entry\n" in md


def test_stack_yaml_route_replaces_the_pack_route(tmp_path):
    st = stack.load(write(tmp_path, "java:\n  routes:\n    - name: spring-web\n      form: annotated\n"
                                    "      when: org.springframework.web.bind.annotation\n      verbs: {GetMapping: GET}\n"
                                    "  tables:\n    - {name: spring-web, regex: '(?P<table>x)'}\n"))
    mine = [p for p in st.patterns if p.lang == "java" and p.name == "spring-web"]
    assert [(p.source, p.verbs) for p in mine] == [("stack.yaml", {"GetMapping": "GET"})]
    # routes and tables are separate name spaces: a table named like a route replaces nothing
    assert [o for o in st.overrides if o.get("group")] == [{"lang": "java", "group": "routes", "name": "spring-web"}]
    # the other languages' entries of that name stay
    assert [p.source for p in st.patterns if p.lang == "kotlin" and p.name == "spring-web"] == ["pack"]


@pytest.mark.parametrize("text,reason", [
    ("scala:\n  tables:\n    - {name: quill, regex: '(?P<table>x)'}\n    - {name: quill, regex: '(?P<table>y)'}\n",
     "duplicate table name"),
    ("java:\n  routes:\n    - {name: jaxrs, path: literal, method: GET, regex: '(?P<path>x)'}\n"
     "    - {name: jaxrs, path: literal, method: GET, regex: '(?P<path>y)'}\n", "duplicate route name"),
    ("python:\n  routes:\n    - {name: fastapi, path: literal, method: GET, regex: '(?P<path>x)'}\n",
     "clashes with a built-in rule"),
    ("scala:\n  routes:\n    - {name: tapir, form: annotated, verbs: {A: GET}}\n", "clashes with a built-in rule"),
])
def test_names_still_clash_within_stack_yaml(tmp_path, text, reason):
    with pytest.raises(stack.StackError, match=reason):
        stack.load(write(tmp_path, text))


def test_spring_stack_section_is_empty(spring_repo):
    """Spring's wiring (`stereotype`, `context`, ...) is the Java pack's to ignore; its IO entries keep their kinds."""
    s = structure.build(spring_repo, "docs/viz-code")
    assert s["stack"]["unrecognised"] == [] and s["stack"]["servers_without_routes"] == []
    st = stack.default()
    for lang in ("java", "kotlin"):
        for t in ("org.springframework.stereotype.Component", "org.springframework.boot.SpringApplication",
                  "org.springframework.context.annotation.Bean", "io.micronaut.context.annotation.Factory",
                  "io.quarkus.runtime.Startup"):
            assert stack.covered(st, lang, t) and stack.sink_kinds(st, lang, t) == [], (lang, t)
        assert [h["kind"] for h in stack.sink_kinds(st, lang, "org.springframework.kafka.annotation.KafkaListener")] \
            == ["event"]


def test_jvm_pack_gaps():
    st = stack.default()
    for lang in ("java", "kotlin"):
        for target, kind in (("jakarta.ws.rs.client.ClientBuilder", "http-out"), ("javax.ws.rs.client.Client", "http-out"),
                             ("jakarta.ws.rs.GET", "http-in"), ("io.micronaut.http.client.HttpClient", "http-out"),
                             ("io.micronaut.http.annotation.Get", "http-in"),
                             ("org.springframework.data.r2dbc.core.R2dbcEntityTemplate", "sql-db")):
            # the longest matching prefix names the kind: `jakarta.ws.rs.client` is a client, not a server
            assert [h["kind"] for h in stack.sink_kinds(st, lang, target)] == [kind], (lang, target)


def test_quill_query_schema():
    st = stack.default()
    src = 'object R {\n  inline def orders = quote(querySchema[Order]("shop.orders", _.id -> "order_id"))\n}\n'
    got = stack.find_tables(st, "scala", src, ["io.getquill"], [(2, 2, "orders")], [(1, 3, "R")], "f")
    assert [(t["table"], t["pattern"]) for t in got] == [("shop.orders", "quill-schema")]
    assert stack.find_tables(st, "scala", src, ["sttp.tapir"], [], [], "f") == []


@pytest.mark.parametrize("imp", ["flask_sqlalchemy", "sqlmodel"])
def test_python_tables_for_flask_sqlalchemy_and_sqlmodel(imp):
    st = stack.default()
    src = "class Order(db.Model):\n    __tablename__ = \"orders\"\n"
    got = stack.find_tables(st, "python", src, [imp], [], [(1, 2, "Order")], "f")
    assert [(t["table"], t["in"], t["kind"]) for t in got] == [("orders", "Order", "defined")]
    # with sqlalchemy also imported, one fact
    both = stack.find_tables(st, "python", src, [imp, "sqlalchemy"], [], [(1, 2, "Order")], "f")
    assert len({(t["table"], t["line"], t["in"]) for t in both}) == 1


def test_stack_yaml_pattern_a_pack_duplicates_is_not_flagged(make_repo):
    """A stack.yaml pattern whose every match a pack pattern also gives is reported as a duplicate of it, not as
    a pattern to check, and is not counted in the Stack heading."""
    from conftest import with_stack
    files = {"pom.xml": "<project/>\n",
             "src/main/java/a/R.java": "package a;\n\nimport jakarta.ws.rs.*;\n\n@Path(\"/r\")\npublic class R {\n"
                                       "  @GET\n  public String x() { return \"\"; }\n}\n",
             "src/main/java/a/T.java": "package a;\n\nimport jakarta.persistence.*;\n\n@Table(name = \"t\")\nclass T {}\n"}
    repo = make_repo(files)
    with_stack(repo, "java:\n  routes:\n    - name: again\n      form: annotated\n      when: jakarta.ws.rs\n"
                     "      prefix: [Path]\n      verbs: {GET: GET}\n"
                     "  tables:\n    - {name: mine, when: jakarta.persistence, regex: '@Table\\(name = \"(?P<table>\\w+)\"'}\n")
    s = structure.build(repo, "docs/viz-code")
    pats = {p["name"]: p for p in s["stack"]["patterns"]}
    assert (pats["again"]["matches"], pats["again"]["duplicates"]) == (0, "jaxrs")
    assert (pats["mine"]["matches"], pats["mine"]["duplicates"]) == (0, "jpa-table-name")
    assert not stack.flagged(pats["again"]) and stack.count(s["stack"]) == 0
    md = structure.summary_md(s)
    assert "- java again (stack.yaml): duplicates jaxrs\n" in md
    assert "- java mine (stack.yaml): duplicates jpa-table-name\n" in md
    assert "## Stack — nothing unrecognised" in md


def test_dedupe_order_is_per_group(make_repo):
    """A table pattern and a route pattern may share a name; each group's dedupe orders its own patterns."""
    from conftest import with_stack
    files = {"pom.xml": "<project/>\n",
             "src/main/java/a/T.java": "package a;\n\nimport jakarta.persistence.*;\n\n@Table(name = \"t\")\nclass T {}\n"}
    repo = make_repo(files)
    with_stack(repo, "java:\n  tables:\n    - {name: jaxrs, when: jakarta.persistence, regex: '@Table\\(name = \"(?P<table>\\w+)\"'}\n")
    s = structure.build(repo, "docs/viz-code")
    assert [(t["table"], t["pattern"]) for t in s["facts"]["src/main/java/a/T.java"]["tables"]] == [
        ("t", "jpa-table-name")]
