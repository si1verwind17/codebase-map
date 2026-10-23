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
                 "    cfg.service(web::resource(\"/site\").route(web::get().to(get_site)));\n}\n",
             "docs/viz-code/stack.yaml":
                 "rust:\n  routes:\n    - name: actix-route\n      when: actix_web\n      path: literal\n"
                 "      method: GET\n      regex: 'resource\\(\"(?P<path>[^\"]*)\"\\)\\.route\\(web::get\\(\\)\\.to\\("
                 "(?P<handler>\\w+)\\)'\n"}
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
