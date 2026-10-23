from vizcode import ids, structure
from vizcode.adapters import generic, python
from vizcode.adapters.langs import SPECS
from vizcode.assemble import assemble

MOD = {"id": "mod:.", "path": ".", "build": "dir"}


def renames(lang, src, rel="x"):
    if lang == "python":
        res = python.parse(src.encode(), rel, {**MOD, "lang": lang}, ids.IdRegistry())
    else:
        res = generic.parse(src.encode(), rel, {**MOD, "lang": lang}, ids.IdRegistry(), spec=SPECS[lang])
    return [(i["target"], i.get("renames")) for i in res["imports"]]


def test_each_language_records_the_names_its_imports_rename():
    assert renames("kotlin", "import io.app.model.Article as ArticleIO\nimport io.app.User\n", "a.kt") == [
        ("io.app.model", {"ArticleIO": "Article"}), ("io.app", None)]
    assert renames("typescript", "import { a as b, c } from './x'\n", "a.ts") == [("./x", {"b": "a"})]
    assert renames("php", "<?php\nuse A\\B\\C as D;\nuse E\\{F, G as H};\n", "a.php") == [
        ("A\\B", {"D": "C"}), ("E", {"H": "G"})]
    assert renames("rust", "use a::b::{c, d as e};\nuse f::g as h;\n", "a.rs") == [
        ("a::b::c", None), ("a::b::d", {"e": "d"}), ("f::g", {"h": "g"})]
    assert renames("csharp", "using X = A.B.C;\nusing A.B;\n", "a.cs") == [("A.B.C", {"X": "C"}), ("A.B", None)]
    assert renames("python", "from app.models import Order as O, Item\n", "a.py") == [
        ("app.models", {"O": "Order"})]


def _service(files, modules=(".",)):
    return {"nodes": [{"id": "svc:app", "kind": "service", "name": "app", "modules": list(modules),
                       "evidence": [{"file": next(iter(files)), "line": 1}]}]}


def test_a_call_through_an_aliased_import_reaches_the_class(make_repo):
    files = {"build.gradle.kts": "\n",
             "src/main/kotlin/io/app/model/Article.kt":
                 "package io.app.model\n\nclass Article {\n    companion object {\n"
                 "        fun fromModel(x: Int): Article = Article()\n    }\n}\n",
             "src/main/kotlin/io/app/web/Handler.kt":
                 "package io.app.web\n\nimport io.app.model.Article as ArticleIO\n\nclass Handler {\n"
                 "    fun view(x: Int) = ArticleIO.fromModel(x)\n}\n"}
    s = structure.build(make_repo(files))
    cmap = assemble(s, _service(files))
    got = {(r["from"].rsplit(".", 1)[-1], r["to"].rsplit(".", 1)[-1])
           for r in cmap["relations"] if r["kind"] == "calls"}
    assert any(f == "Handler#view/1" and t.endswith("#fromModel/1") for f, t in got), got


def test_a_route_handler_class_through_an_alias_and_a_namespace(make_repo):
    """`use ..\\API\\ScrobbleController as ApiScrobble` names the API one of two same-named controllers."""
    ctrl = ("<?php\n\nnamespace App\\Http\\Controllers{ns};\n\nclass ScrobbleController\n{{\n"
            "    public function store() {{}}\n}}\n")
    files = {"composer.json": "{\"name\": \"demo/app\"}\n",
             "app/Http/Controllers/ScrobbleController.php": ctrl.format(ns=""),
             "app/Http/Controllers/API/ScrobbleController.php": ctrl.format(ns="\\API"),
             "routes/api.php": "<?php\n\nuse App\\Http\\Controllers\\API\\ScrobbleController as ApiScrobble;\n"
                               "use Illuminate\\Support\\Facades\\Route;\n\n"
                               "Route::post('/scrobble', [ApiScrobble::class, 'store']);\n"}
    s = structure.build(make_repo(files))
    assert [r["handler"] for r in s["facts"]["routes/api.php"]["routes"]] == [
        ".::App\\Http\\Controllers\\API.ScrobbleController#store/0"]


def test_a_route_handler_in_another_module_its_file_imports(make_repo):
    files = {"Cargo.toml": "[workspace]\nmembers = [\"crates/routes\", \"crates/api\"]\n",
             "crates/api/Cargo.toml": "[package]\nname = \"app_api\"\n",
             "crates/api/src/lib.rs": "pub mod site;\n",
             "crates/api/src/site.rs": "pub async fn get_site() {}\npub async fn other() {}\n",
             "crates/routes/Cargo.toml": "[package]\nname = \"app_routes\"\n",
             "crates/routes/src/lib.rs":
                 "use actix_web::web;\nuse app_api::site::get_site;\n\n"
                 "pub fn config(cfg: &mut web::ServiceConfig) {\n"
                 "    cfg.service(web::resource(\"/site\").route(web::get().to(get_site)));\n}\n"}
    s = structure.build(make_repo(files), "docs/viz-code")
    assert [r["handler"] for r in s["facts"]["crates/routes/src/lib.rs"]["routes"]] == [
        "crates/api::src/site.rs#get_site/0"]


def _calls(s):
    return {(c["in"].rsplit("::", 1)[-1], c["callee"]) for ff in s["facts"].values() for c in ff.get("calls", [])}


def test_an_aliased_base_class_resolves_and_an_external_alias_is_left_alone(make_repo):
    files = {"package.json": "{\"name\": \"web\"}\n",
             "src/base.ts": "export class BaseService {\n  helper() { return 1 }\n}\n",
             "src/foo.ts": "import { BaseService as Base } from './base'\nimport { join as joinPath } from 'path'\n\n"
                           "export class Foo extends Base {\n  run() { return this.helper() }\n"
                           "  build() { return joinPath('a') }\n}\n\nexport function join() { return 2 }\n"}
    s = structure.build(make_repo(files))
    foo = next(n for n in s["nodes"] if n["kind"] == "class" and n["name"] == "Foo")
    assert [i.rsplit(".", 1)[-1] for i in foo.get("implements", [])] == ["BaseService"]
    assert ("src.foo.Foo#build/0", "joinPath") in _calls(s)


def test_a_laravel_alias_beside_a_plain_import_of_the_same_name(make_repo):
    ctrl = ("<?php\n\nnamespace App\\Http\\Controllers{ns};\n\nclass UserController\n{{\n"
            "    public function index() {{}}\n}}\n")
    files = {"composer.json": "{\"name\": \"demo/app\"}\n",
             "app/Http/Controllers/UserController.php": ctrl.format(ns=""),
             "app/Http/Controllers/Admin/UserController.php": ctrl.format(ns="\\Admin"),
             "routes/web.php": "<?php\n\nuse App\\Http\\Controllers\\UserController;\n"
                               "use App\\Http\\Controllers\\Admin\\UserController as AdminUserController;\n"
                               "use Illuminate\\Support\\Facades\\Route;\n\n"
                               "Route::get('/users', [UserController::class, 'index']);\n"
                               "Route::get('/admin/users', [AdminUserController::class, 'index']);\n"}
    s = structure.build(make_repo(files))
    assert [(r["path"], r["handler"]) for r in s["facts"]["routes/web.php"]["routes"]] == [
        ("/users", ".::App\\Http\\Controllers.UserController#index/0"),
        ("/admin/users", ".::App\\Http\\Controllers\\Admin.UserController#index/0")]


def test_a_handler_imported_from_outside_the_repo_is_not_found_in_another_service(make_repo):
    files = {"a/go.mod": "module example.com/a\n", "b/go.mod": "module example.com/b\n",
             "a/main.go": "package main\n\nimport (\n\t\"github.com/gin-gonic/gin\"\n"
                          "\t\"github.com/vendor/kit/handlers\"\n)\n\n"
                          "func main() {\n\tr := gin.Default()\n\tr.GET(\"/health\", handlers.Health)\n}\n",
             "b/handlers/health.go": "package handlers\n\nfunc Health() {}\n"}
    s = structure.build(make_repo(files))
    assert [r["handler"].split("::")[0] for r in s["facts"]["a/main.go"]["routes"]] == ["a"]


def test_interfaces_a_framework_implements_are_listed(make_repo):
    """A declarative HTTP client or a repository interface (every method bodyless) in a file importing an HTTP
    client or database library is listed in summary.md with its annotation, bases and methods: its methods are
    where a request or a table access starts."""
    files = {"pom.xml": "<project/>\n",
             "src/main/java/a/StatsClient.java":
                 "package a;\n\nimport org.springframework.cloud.openfeign.FeignClient;\n\n"
                 "@FeignClient(name = \"statistics-service\")\npublic interface StatsClient {\n"
                 "    @PutMapping(\"/statistics/{name}\")\n    void update(String name, Account account);\n}\n",
             "src/main/java/a/AccountRepository.java":
                 "package a;\n\nimport org.springframework.data.mongodb.repository.MongoRepository;\n\n"
                 "public interface AccountRepository extends MongoRepository<Account, String> {\n"
                 "    Account findByName(String name);\n}\n",
             "src/main/java/a/Account.java": "package a;\n\npublic class Account {\n    void touch() {}\n}\n"}
    s = structure.build(make_repo(files))
    got = {f: ff.get("implemented") for f, ff in s["facts"].items() if ff.get("implemented")}
    assert got == {
        "src/main/java/a/StatsClient.java": [{"class": "StatsClient", "line": 5, "methods": ["update"], "bases": [],
                                              "annotation": '@FeignClient(name = "statistics-service")'}],
        "src/main/java/a/AccountRepository.java": [{"class": "AccountRepository", "line": 5, "methods": ["findByName"],
                                                    "bases": ["MongoRepository"], "annotation": None}]}
    md = structure.summary_md(s)
    assert "- **framework-implemented interfaces:** AccountRepository extends MongoRepository [findByName] " \
           "(src/main/java/a/AccountRepository.java:5); " \
           'StatsClient @FeignClient(name = "statistics-service") [update] (src/main/java/a/StatsClient.java:5)' in md


def test_a_declarative_client_s_mappings_are_no_route_looking_lines(make_repo):
    """`@PostMapping("/payments")` on a `@FeignClient` interface's method is a call out, not a route missed."""
    files = {"pom.xml": "<project/>\n",
             "src/main/java/a/PaymentsClient.java":
                 "package a;\n\nimport org.springframework.cloud.openfeign.FeignClient;\n"
                 "import org.springframework.web.bind.annotation.PostMapping;\n\n"
                 "@FeignClient(name = \"payments\", url = \"${payments.url}\")\npublic interface PaymentsClient {\n"
                 "    @PostMapping(\"/payments\")\n    Receipt charge(Charge c);\n}\n"}
    s = structure.build(make_repo(files))
    assert s["stack"]["routes_unmatched"] == []


def test_a_queue_created_outside_any_method_sits_in_its_file_node():
    """A queue made in a class field or at file level: its site is the file's node, never the placeholder (a NUL
    byte in summary.md made the file read as binary)."""
    from vizcode import ids
    r = {"nodes": [], "package": "src", "routes": [], "tables": [],
         "queues": [{"line": 3, "in": structure.NEW_FILE_NODE, "delivery": "fan-out"}]}
    structure._file_node(r, "src/bus.ts", "mod:.", "typescript", 10, ids.IdRegistry())
    assert r["queues"][0]["in"] == r["nodes"][0]["id"] and "\0" not in r["queues"][0]["in"]
