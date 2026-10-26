"""Type links on method signatures (spec: traces §1.2): `refs` per parameter, `returns_refs` on the signature."""
import pytest

from vizcode.scan import structure
from vizcode.scan.typelinks import dotted, names_import, qualified, type_names


def build(make_repo, files: dict[str, str]) -> dict:
    return structure.build(make_repo(files), "docs/viz-code")


def method(s: dict, name: str, file: str) -> dict:
    hits = [n for n in s["nodes"] if n["kind"] == "method" and n["name"] == name and n["file"] == file]
    assert len(hits) == 1, [n["id"] for n in hits]
    return hits[0]


def links(s: dict, name: str, file: str) -> tuple[list, list]:
    """([refs of each parameter, as `file:Class`], returns_refs as `file:Class`); a missing key reads as []."""
    by_id = {n["id"]: n for n in s["nodes"]}
    sig = method(s, name, file)["signature"]
    show = lambda ids_: [f"{by_id[i]['file']}:{by_id[i]['name']}" for i in ids_]   # noqa: E731
    return [show(p.get("refs", [])) for p in sig["params"]], show(sig.get("returns_refs", []))


def test_type_names_are_each_identifier_once_in_order():
    assert type_names("Map[BayId, List[BayId]]") == ["Map", "BayId", "List"]
    assert type_names("Result<Vec<models::Charge>, Error>") == ["Result", "Vec", "models", "Charge", "Error"]
    assert type_names(None) == [] and type_names("") == []


def test_dotted_and_qualified():
    assert dotted("crate::models::Charge") == "models.Charge"
    assert dotted("App\\Models\\Charge") == "App.Models.Charge"
    assert dotted("../models/charge") == "models.charge"
    assert dotted(".models.Quote") == "models.Quote"
    assert qualified("svc::internal/orders.Repo") == "internal.orders.Repo"


@pytest.mark.parametrize("qname,name,path,want", [
    ("a.model.Charge", "Charge", "a.model.Charge", True),                       # explicit
    ("a.model.Charge", "Charge", "a.model", True),                              # wildcard / namespace
    ("internal.orders.Order", "Order", "example.com.shop.internal.orders", True),   # Go import path
    ("a.model.Charge", "Charge", "a.model.Other", False),                       # another class of that package
    ("a.model.Charge", "Charge", "b.model.Charge", False),
])
def test_names_import(qname, name, path, want):
    assert names_import(qname, name, path) is want


SCALA = {
    "build.sbt": 'lazy val common = (project in file("common"))\n'
                 'lazy val shop = (project in file("shop")).dependsOn(common)\n',
    "common/src/main/scala/city/common/Money.scala": "package city.common\n\nfinal case class Money(cents: Long)\n",
    "shop/src/main/scala/city/shop/model/Reservation.scala":
        "package city.shop.model\n\nfinal case class BayId(value: String)\n"
        "final case class Reservation(id: String, bay: BayId)\n",
    "shop/src/main/scala/city/shop/a/Status.scala": "package city.shop.a\n\nfinal case class Status(v: Int)\n",
    "shop/src/main/scala/city/shop/b/Status.scala": "package city.shop.b\n\nfinal case class Status(v: Int)\n",
    "shop/src/main/scala/city/shop/api/Quote.scala": "package city.shop.api\n\nfinal case class Quote(total: Long)\n",
    "shop/src/main/scala/city/shop/api/ReservationApi.scala":
        "package city.shop.api\n\nimport city.shop.model.{BayId, Reservation}\nimport zio.*\n\n"
        "final case class Local(n: Int)\n\n"
        "trait ReservationApi {\n"
        "  def reserve(r: Reservation, byBay: Map[BayId, Status], price: Money): Task[List[Reservation]]\n"
        "  def quote(l: Local, raw: String): Option[Quote]\n}\n",
}


def test_scala_levels_wrapped_types_and_unresolved(make_repo):
    s = build(make_repo, SCALA)
    api = "shop/src/main/scala/city/shop/api/ReservationApi.scala"
    model = "shop/src/main/scala/city/shop/model/Reservation.scala"
    params, returns = links(s, "reserve", api)
    # import (braces: the package), wrapped types; `Status` is in two packages, neither imported: unresolved;
    # `Money` is unique in the repo (another module); `Map`, `Task`, `List` are no repo classes
    assert params == [[f"{model}:Reservation"], [f"{model}:BayId"],
                      ["common/src/main/scala/city/common/Money.scala:Money"]]
    assert returns == [f"{model}:Reservation"]
    params, returns = links(s, "quote", api)
    # same file, then same package; a parameter with no repo class has no `refs` key
    assert params == [[f"{api}:Local"], []]
    assert returns == ["shop/src/main/scala/city/shop/api/Quote.scala:Quote"]
    sig = method(s, "quote", api)["signature"]
    assert "refs" not in sig["params"][1]


def test_scala_same_name_in_two_packages_resolves_by_import(make_repo):
    files = {**SCALA, "shop/src/main/scala/city/shop/api/Uses.scala":
             "package city.shop.api\n\nimport city.shop.b.Status\n\nobject Uses {\n  def s(x: Status): Status = x\n}\n"}
    s = build(make_repo, files)
    params, returns = links(s, "s", "shop/src/main/scala/city/shop/api/Uses.scala")
    assert params == [["shop/src/main/scala/city/shop/b/Status.scala:Status"]]
    assert returns == ["shop/src/main/scala/city/shop/b/Status.scala:Status"]


def test_python_import_untyped_and_other_family(make_repo):
    s = build(make_repo, {
        "pyproject.toml": '[project]\nname = "shop"\nversion = "0.1"\n',
        "shop/__init__.py": "",
        "shop/models.py": "from dataclasses import dataclass\n\n\n@dataclass\nclass Quote:\n    total: int\n",
        "shop/service.py": "from shop.models import Quote\n\n\n"
                           "def price(q: Quote, raw, n: int) -> list[Quote]:\n    return [q]\n\n\n"
                           "def other(c: \"Charge\") -> dict:\n    return {}\n",
        "web/package.json": '{"name": "web"}\n',
        "web/src/charge.ts": "export interface Charge { id: string }\n",
    })
    params, returns = links(s, "price", "shop/service.py")
    assert params == [["shop/models.py:Quote"], [], []]
    assert returns == ["shop/models.py:Quote"]
    # a TypeScript `Charge` is not a Python type
    assert links(s, "other", "shop/service.py") == ([[]], [])


def test_java_wildcard_import_and_kotlin_same_package(make_repo):
    s = build(make_repo, {
        "pom.xml": "<project><modules><module>api</module></modules></project>\n",
        "api/pom.xml": "<project><artifactId>api</artifactId></project>\n",
        "api/src/main/java/a/model/Charge.java": "package a.model;\n\npublic record Charge(String id) {}\n",
        "api/src/main/java/a/other/Charge.java": "package a.other;\n\npublic record Charge(String id) {}\n",
        "api/src/main/java/a/web/Pay.java":
            "package a.web;\n\nimport a.model.*;\nimport java.util.concurrent.Future;\n\n"
            "public class Pay {\n  public Future<Charge> pay(Charge c) { return null; }\n}\n",
        "api/src/main/kotlin/a/web/Refund.kt":
            "package a.web\n\nclass Refund {\n  fun refund(p: Pay): List<Pay> = listOf(p)\n}\n",
    })
    pay = "api/src/main/java/a/web/Pay.java"
    charge = "api/src/main/java/a/model/Charge.java:Charge"
    assert links(s, "pay", pay) == ([[charge]], [charge])
    # Kotlin and Java are one family: same package
    assert links(s, "refund", "api/src/main/kotlin/a/web/Refund.kt") == ([[f"{pay}:Pay"]], [f"{pay}:Pay"])


def test_typescript_relative_import_picks_the_imported_file(make_repo):
    s = build(make_repo, {
        "package.json": '{"name": "web"}\n',
        "src/models/charge.ts": "export interface Charge { id: string }\n",
        "src/legacy/charge.ts": "export interface Charge { old: string }\n",
        "src/pay.ts": "import { Charge } from './models/charge';\n\n"
                      "export async function pay(c: Charge, n: number): Promise<Charge[]> { return [c]; }\n",
        "src/plain.js": "export function f(a, b) { return a; }\n",
    })
    assert links(s, "pay", "src/pay.ts") == ([["src/models/charge.ts:Charge"], []], ["src/models/charge.ts:Charge"])
    assert links(s, "f", "src/plain.js") == ([[], []], [])


def test_go_import_path(make_repo):
    s = build(make_repo, {
        "go.mod": "module example.com/shop\n\ngo 1.22\n",
        "internal/orders/order.go": "package orders\n\ntype Charge struct {\n\tID string\n}\n\n"
                                    "type Receipt struct {\n\tN int\n}\n",
        "internal/api/handler.go": "package api\n\nimport \"example.com/shop/internal/orders\"\n\n"
                                   "type Handler struct{}\n\n"
                                   "func (h *Handler) Pay(c orders.Charge) (*orders.Receipt, error) { return nil, nil }\n",
    })
    got = links(s, "Pay", "internal/api/handler.go")
    assert got == ([["internal/orders/order.go:Charge"]], ["internal/orders/order.go:Receipt"])


def test_csharp_using_namespace(make_repo):
    s = build(make_repo, {
        "Shop.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
        "Models/Charge.cs": "namespace Shop.Models;\n\npublic record Charge(string Id);\n",
        "Api/PayController.cs": "using Shop.Models;\n\nnamespace Shop.Api;\n\npublic class PayController {\n"
                                "  public Task<Charge> Pay(Charge c) => null;\n}\n",
    })
    assert links(s, "Pay", "Api/PayController.cs") == ([["Models/Charge.cs:Charge"]], ["Models/Charge.cs:Charge"])


def test_rust_use_path(make_repo):
    s = build(make_repo, {
        "Cargo.toml": "[package]\nname = \"shop\"\nversion = \"0.1.0\"\n",
        "src/models.rs": "pub struct Charge { pub id: String }\n",
        "src/main.rs": "mod models;\nuse crate::models::Charge;\n\n"
                       "pub fn pay(c: Charge) -> Result<Vec<Charge>, String> { Ok(vec![c]) }\n",
    })
    assert links(s, "pay", "src/main.rs") == ([["src/models.rs:Charge"]], ["src/models.rs:Charge"])


def test_php_use(make_repo):
    s = build(make_repo, {
        "composer.json": '{"name": "acme/shop"}\n',
        "src/Models/Charge.php": "<?php\nnamespace App\\Models;\n\nclass Charge { public string $id; }\n",
        "src/Http/PayController.php": "<?php\nnamespace App\\Http;\n\nuse App\\Models\\Charge;\n\n"
                                      "class PayController {\n  public function pay(Charge $c): ?Charge { return $c; }\n}\n",
    })
    assert links(s, "pay", "src/Http/PayController.php") == ([["src/Models/Charge.php:Charge"]],
                                                              ["src/Models/Charge.php:Charge"])


def test_ruby_signatures_have_no_refs(make_repo):
    s = build(make_repo, {
        "Gemfile": "source 'https://rubygems.org'\n",
        "lib/charge.rb": "class Charge\n  def initialize(id)\n    @id = id\n  end\nend\n",
        "lib/pay.rb": "class Pay\n  def pay(charge)\n    charge\n  end\nend\n",
    })
    assert links(s, "pay", "lib/pay.rb") == ([[]], [])


def test_single_letter_type_parameters_never_resolve(make_repo):
    s = build(make_repo, {
        "package.json": '{"name": "web"}\n',
        "src/t.ts": "export class T { id = 1 }\n",
        "src/g.ts": "export function g<T>(c: T): T { return c; }\n",
        "build.sbt": 'lazy val shop = (project in file("shop"))\n',
        "shop/src/main/scala/city/shop/T.scala": "package city.shop\n\nfinal case class T(v: Int)\n",
        "shop/src/main/scala/city/shop/G.scala":
            "package city.shop\n\nobject G {\n  def g[T](x: T): Option[T] = Some(x)\n}\n",
    })
    assert links(s, "g", "src/g.ts") == ([[]], [])
    assert links(s, "g", "shop/src/main/scala/city/shop/G.scala") == ([[]], [])


def test_python_relative_imports_anchor_on_the_importing_package(make_repo):
    s = build(make_repo, {
        "pyproject.toml": '[project]\nname = "shop"\nversion = "0.1"\n',
        "shop/__init__.py": "",
        "shop/a/__init__.py": "",
        "shop/b/__init__.py": "",
        "shop/a/models.py": "class Quote:\n    total: int\n",
        "shop/b/models.py": "class Quote:\n    total: int\n",
        "shop/a/svc.py": "from .models import Quote\n\n\ndef f(q: Quote) -> Quote:\n    return q\n",
        "shop/a/mod.py": "from . import models\n\n\ndef h(q: models.Quote):\n    return q\n",
        "shop/b/deep/__init__.py": "",
        "shop/b/deep/svc.py": "from ..models import Quote\n\n\ndef g(q: Quote) -> Quote:\n    return q\n",
        "shop/c.py": "from .a.models import Quote\n\n\ndef k(q: Quote):\n    return q\n",
    })
    a, b = "shop/a/models.py:Quote", "shop/b/models.py:Quote"
    assert links(s, "f", "shop/a/svc.py") == ([[a]], [a])
    assert links(s, "h", "shop/a/mod.py") == ([[a]], [])
    assert links(s, "g", "shop/b/deep/svc.py") == ([[b]], [b])
    assert links(s, "k", "shop/c.py") == ([[a]], [])


def test_scala_objects_and_anonymous_classes_are_not_targets(make_repo):
    s = build(make_repo, {
        "build.sbt": 'lazy val shop = (project in file("shop"))\n',
        "shop/src/main/scala/city/shop/Codec.scala":
            "package city.shop\n\nobject Codec {\n  val c = 1\n}\n\n"
            "object Make {\n  val x = new Runnable { def run(): Unit = () }\n}\n",
        "shop/src/main/scala/city/shop/Use.scala":
            "package city.shop\n\nobject Use {\n  def u(c: Codec, r: Runnable): Make = null\n}\n",
    })
    assert links(s, "u", "shop/src/main/scala/city/shop/Use.scala") == ([[], []], [])


def test_go_library_qualified_names_never_link_by_last_name(make_repo):
    s = build(make_repo, {
        "go.mod": "module example.com/shop\n\ngo 1.22\n",
        "internal/api/types.go": "package api\n\ntype Request struct {\n\tID string\n}\n\n"
                                 "type Context struct {\n\tN int\n}\n",
        "internal/store/duration.go": "package store\n\ntype Duration struct {\n\tN int64\n}\n",
        "internal/api/handler.go":
            "package api\n\nimport (\n\t\"context\"\n\t\"net/http\"\n\t\"time\"\n\n"
            "\t\"example.com/shop/internal/store\"\n)\n\n"
            "func Serve(ctx context.Context, r *http.Request, d time.Duration) error { return nil }\n\n"
            "func Keep(d store.Duration, r Request) store.Duration { return d }\n",
    })
    handler = "internal/api/handler.go"
    assert links(s, "Serve", handler) == ([[], [], []], [])
    # an imported package names the class's package; an unqualified name still resolves in the same package
    dur = "internal/store/duration.go:Duration"
    assert links(s, "Keep", handler) == ([[dur], ["internal/api/types.go:Request"]], [dur])


def test_scala_fully_qualified_library_type(make_repo):
    s = build(make_repo, {
        "build.sbt": 'lazy val shop = (project in file("shop"))\n',
        "shop/src/main/scala/city/shop/Instant.scala": "package city.shop\n\nfinal case class Instant(v: Long)\n",
        "shop/src/main/scala/city/shop/Clock.scala":
            "package city.shop\n\nobject Clock {\n  def now(at: java.time.Instant): city.shop.Instant = null\n}\n",
    })
    assert links(s, "now", "shop/src/main/scala/city/shop/Clock.scala") == (
        [[]], ["shop/src/main/scala/city/shop/Instant.scala:Instant"])


PY_TWO_SERVICES = {
    "pyproject.toml": '[project]\nname = "shop"\nversion = "0.1"\n',
    "shop/__init__.py": "",
    "shop/http.py": "class Request:\n    path: str\n\n\nclass Module:\n    name: str\n",
}


def test_python_explicit_library_import_and_module_qualified_names(make_repo):
    s = build(make_repo, {
        **PY_TWO_SERVICES,
        "shop/web.py": "import ast\nfrom fastapi import Request\n\n\n"
                       "def handle(r: Request, tree: ast.Module) -> Request:\n    return r\n",
    })
    assert links(s, "handle", "shop/web.py") == ([[], []], [])


def test_python_imported_module_and_package_prefixes(make_repo):
    s = build(make_repo, {
        "pyproject.toml": '[project]\nname = "pkg"\nversion = "0.1"\n',
        "pkg/__init__.py": "",
        "pkg/nodes.py": "class Item:\n    name: str\n",
        "pkg/other.py": "class Item:\n    name: str\n",
        "pkg/run.py": "from pkg import nodes\n\n\ndef collect(i: nodes.Item) -> \"nodes.Item\":\n    return i\n",
    })
    item = "pkg/nodes.py:Item"
    assert links(s, "collect", "pkg/run.py") == ([[item]], [item])


def test_python_local_type_alias_never_links(make_repo):
    s = build(make_repo, {
        **PY_TWO_SERVICES,
        "shop/token.py": "class TokenType:\n    kind: str\n",
        "shop/lexer.py": "from typing import Tuple, TypeVar\n\nTokenType = Tuple[str, ...]\nModule = TypeVar(\"Module\")\n\n\n"
                         "def lex(t: TokenType, m: Module) -> TokenType:\n    return t\n",
    })
    assert links(s, "lex", "shop/lexer.py") == ([[], []], [])


def test_python_literal_strings_unresolved_forward_refs_resolve(make_repo):
    s = build(make_repo, {
        "pyproject.toml": '[project]\nname = "shop"\nversion = "0.1"\n',
        "shop/__init__.py": "",
        "shop/models.py": "class Charge:\n    id: str\n\n\nclass Date:\n    v: int\n",
        "shop/svc.py": "from typing import List, Literal\nfrom shop.models import Charge, Date\n\n\n"
                       "def kind(k: Literal[\"Charge\"], d: \"Date\", ds: List[\"Date\"]) -> Literal['Charge', 'Date']:\n"
                       "    return k\n",
    })
    date = "shop/models.py:Date"
    assert links(s, "kind", "shop/svc.py") == ([[], [date], [date]], [])


TS_STORE = {
    "package.json": '{"name": "web"}\n',
    "src/store.ts": "export interface Store { name: string }\n",
    "src/order.ts": "export interface Order { id: string }\n",
    "src/charge.ts": "export interface Charge { id: string }\n",
}


def test_typescript_string_union_aliases_and_literal_types(make_repo):
    s = build(make_repo, {
        **TS_STORE,
        "src/kinds.ts": "export type Kind = \"database\" | \"cache\";\n",
        "src/other/kinds.ts": "export interface Kind { k: string }\n",
        "src/local.ts": "type Store = \"database\" | \"cache\";\n\n"
                        "export function pick(s: Store, t: 'Order' | 'Charge'): `Order` { return 'Order'; }\n",
        "src/imported.ts": "import { Kind } from './kinds';\nimport { Request } from 'express';\n\n"
                           "export function use(k: Kind, r: Request): Kind { return k; }\n",
        "src/request.ts": "export interface Request { url: string }\n",
    })
    assert links(s, "pick", "src/local.ts") == ([[], []], [])
    assert links(s, "use", "src/imported.ts") == ([[], []], [])


def test_rust_qualified_paths(make_repo):
    s = build(make_repo, {
        "Cargo.toml": "[package]\nname = \"shop\"\nversion = \"0.1.0\"\n",
        "src/models.rs": "pub struct Charge { pub id: String }\npub struct Duration { pub n: u64 }\n",
        "src/main.rs": "mod models;\n\n"
                       "pub fn pay(c: crate::models::Charge, d: std::time::Duration) -> Vec<models::Charge> { vec![c] }\n",
    })
    charge = "src/models.rs:Charge"
    assert links(s, "pay", "src/main.rs") == ([[charge], []], [charge])


def test_typescript_barrel_import_still_resolves(make_repo):
    s = build(make_repo, {
        "package.json": '{"name": "web"}\n',
        "src/models/charge.ts": "export interface Charge { id: string }\n",
        "src/models/index.ts": "export * from './charge';\n",
        "src/pay.ts": "import { Charge } from './models';\n\nexport function pay(c: Charge): void {}\n",
    })
    assert links(s, "pay", "src/pay.ts") == ([["src/models/charge.ts:Charge"]], [])


@pytest.mark.parametrize("files,file,name", [
    ({"build.sbt": 'lazy val shop = (project in file("shop"))\n',
      "shop/src/main/scala/city/other/Money.scala": "package city.other\n\nfinal case class Money(v: Long)\n",
      "shop/src/main/scala/city/shop/Pay.scala":
          "package city.shop\n\nobject Pay {\n  type Money = Long\n  def pay(m: Money): Unit = ()\n}\n"},
     "shop/src/main/scala/city/shop/Pay.scala", "pay"),
    ({"settings.gradle.kts": "rootProject.name = \"shop\"\n",
      "src/main/kotlin/a/other/Money.kt": "package a.other\n\nclass Money(val v: Long)\n",
      "src/main/kotlin/a/pay/Pay.kt": "package a.pay\n\ntypealias Money = Long\n\nfun pay(m: Money) {}\n"},
     "src/main/kotlin/a/pay/Pay.kt", "pay"),
    ({"Cargo.toml": "[package]\nname = \"shop\"\nversion = \"0.1.0\"\n",
      "src/other.rs": "pub struct Money { pub v: u64 }\n",
      "src/main.rs": "type Money = u64;\n\npub fn pay(m: Money) {}\n"},
     "src/main.rs", "pay"),
])
def test_local_type_aliases_never_link(make_repo, files, file, name):
    assert links(build(make_repo, files), name, file) == ([[]], [])


@pytest.mark.parametrize("files,file", [
    ({"package.json": '{"name": "web"}\n',
      "tsconfig.json": '{"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["src/*"]}}}\n',
      "src/models/charge.ts": "export interface Charge { id: string }\n",
      "src/pay.ts": "import { Charge } from '@/models/charge';\n\nexport function pay(c: Charge): void {}\n"},
     "src/pay.ts"),
    ({"package.json": '{"name": "root", "workspaces": ["packages/*"]}\n',
      "packages/models/package.json": '{"name": "@acme/models"}\n',
      "packages/models/src/charge.ts": "export interface Charge { id: string }\n",
      "packages/web/package.json": '{"name": "@acme/web"}\n',
      "packages/web/src/pay.ts": "import { Charge } from '@acme/models';\n\nexport function pay(c: Charge): void {}\n"},
     "packages/web/src/pay.ts"),
])
def test_typescript_path_alias_and_workspace_imports_are_internal(make_repo, files, file):
    params, _ = links(build(make_repo, files), "pay", file)
    assert [p[0].rsplit(":", 1)[1] for p in params] == ["Charge"]


SCALA_INSTANT = {
    "build.sbt": 'lazy val shop = (project in file("shop"))\n',
    "shop/src/main/scala/city/shop/Instant.scala": "package city.shop\n\nfinal case class Instant(v: Long)\n",
    "shop/src/main/scala/city/model/Order.scala": "package city.model\n\nfinal case class Order(id: String)\n"
                                                  "final case class Quote(total: Long)\n"
                                                  "final case class Refund(id: String)\n",
}


def test_scala_brace_imports_name_their_members(make_repo):
    s = build(make_repo, {
        **SCALA_INSTANT,
        "shop/src/main/scala/city/shop/Clock.scala":
            "package city.shop\n\nimport java.time.{Instant, Duration}\nimport city.model.{Order, Quote => Q}\n"
            "import city.model.{Refund, _}\n\n"
            "object Clock {\n  def now(at: Instant, o: Order, q: Q, r: Refund): Quote = null\n}\n",
    })
    model = "shop/src/main/scala/city/model/Order.scala"
    assert links(s, "now", "shop/src/main/scala/city/shop/Clock.scala") == (
        [[], [f"{model}:Order"], [], [f"{model}:Refund"]], [f"{model}:Quote"])


def test_namespace_and_aliased_imports_name_qualified_prefixes(make_repo):
    s = build(make_repo, {
        "package.json": '{"name": "web"}\n',
        "src/models/charge.ts": "export interface Charge { id: string }\n",
        "src/legacy/charge.ts": "export interface Charge { id: string }\n",
        "src/pay.ts": "import * as models from './models/charge';\n\n"
                      "export function pay(c: models.Charge): void {}\n",
        "pyproject.toml": '[project]\nname = "pkg"\nversion = "0.1"\n',
        "pkg/__init__.py": "",
        "pkg/m.py": "class Charge:\n    a: int\n",
        "pkg/x.py": "class Charge:\n    a: int\n",
        "pkg/s.py": "import pkg.m as mm\n\n\ndef s(c: mm.Charge) -> None:\n    pass\n",
        "go.mod": "module example.com/shop\n\ngo 1.22\n",
        "internal/store/d.go": "package store\n\ntype Duration struct {\n\tN int\n}\n",
        "internal/other/d.go": "package other\n\ntype Duration struct {\n\tN int\n}\n",
        "internal/b/h.go": "package b\n\nimport st \"example.com/shop/internal/store\"\n\nfunc H(d st.Duration) {}\n",
    })
    assert links(s, "pay", "src/pay.ts") == ([["src/models/charge.ts:Charge"]], [])
    assert links(s, "s", "pkg/s.py") == ([["pkg/m.py:Charge"]], [])
    assert links(s, "H", "internal/b/h.go") == ([["internal/store/d.go:Duration"]], [])


def test_library_qualified_names_never_link_to_a_same_named_repo_folder(make_repo):
    s = build(make_repo, {
        "go.mod": "module example.com/shop\n\ngo 1.22\n",
        "internal/log/logger.go": "package log\n\ntype Logger struct {\n\tN int\n}\n",
        "internal/api/handler.go": "package api\n\nimport \"log\"\n\nfunc Serve(l *log.Logger) error { return nil }\n",
        "internal/api/keep.go": "package api\n\nimport \"example.com/shop/internal/log\"\n\n"
                                "func Keep(l *log.Logger) error { return nil }\n",
    })
    assert links(s, "Serve", "internal/api/handler.go") == ([[]], [])
    assert links(s, "Keep", "internal/api/keep.go") == ([["internal/log/logger.go:Logger"]], [])


def test_python_library_module_never_links_to_a_same_named_repo_module(make_repo):
    s = build(make_repo, {
        "pyproject.toml": '[project]\nname = "shop"\nversion = "0.1"\n',
        "shop/__init__.py": "",
        "shop/logging.py": "class Logger:\n    name: str\n",
        "shop/web.py": "import logging\n\n\ndef handle(l: logging.Logger) -> None:\n    return None\n",
        "shop/app.py": "from shop import logging\n\n\ndef keep(l: logging.Logger) -> None:\n    return None\n",
        "shop/named.py": "from logging import Logger\n\n\ndef named(l: Logger) -> None:\n    return None\n",
    })
    assert links(s, "handle", "shop/web.py") == ([[]], [])
    assert links(s, "named", "shop/named.py") == ([[]], [])
    assert links(s, "keep", "shop/app.py") == ([["shop/logging.py:Logger"]], [])


TYPE_PARAM_CASES = {
    "java": ({"pom.xml": "<project><artifactId>api</artifactId></project>\n",
              "src/main/java/a/ev/TEvent.java": "package a.ev;\n\npublic record TEvent(String id) {}\n",
              "src/main/java/a/ev/Bus.java": "package a.ev;\n\npublic class Bus<TEvent extends Object> {\n"
                                             "  public TEvent publish(TEvent e) { return e; }\n}\n",
              "src/main/java/a/ev/Handler.java": "package a.ev;\n\npublic class Handler {\n"
                                                 "  public <TEvent> TEvent handle(TEvent e) { return e; }\n"
                                                 "  public TEvent keep(TEvent e) { return e; }\n}\n"},
             "src/main/java/a/ev/"),
    "kotlin": ({"build.gradle.kts": "plugins { kotlin(\"jvm\") }\n",
                "src/main/kotlin/a/ev/TEvent.kt": "package a.ev\n\ndata class TEvent(val id: String)\n",
                "src/main/kotlin/a/ev/Bus.kt": "package a.ev\n\nclass Bus<TEvent> {\n"
                                               "  fun publish(e: TEvent): TEvent = e\n}\n",
                "src/main/kotlin/a/ev/Handler.kt": "package a.ev\n\nclass Handler {\n"
                                                   "  fun <TEvent> handle(e: TEvent): TEvent = e\n"
                                                   "  fun keep(e: TEvent): TEvent = e\n}\n"},
               "src/main/kotlin/a/ev/"),
    "typescript": ({"package.json": '{"name": "web"}\n',
                    "src/TEvent.ts": "export class TEvent { id = \"\" }\n",
                    "src/Bus.ts": "export class Bus<TEvent> {\n  publish(e: TEvent): TEvent { return e; }\n}\n",
                    "src/Handler.ts": "export function handle<TEvent>(e: TEvent): TEvent { return e; }\n"
                                      "export function keep(e: TEvent): TEvent { return e; }\n"},
                   "src/"),
    "csharp": ({"Shop.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
                "TEvent.cs": "namespace Shop;\n\npublic record TEvent(string Id);\n",
                "Bus.cs": "namespace Shop;\n\npublic class Bus<TEvent> {\n  public TEvent Publish(TEvent e) => e;\n}\n",
                "Handler.cs": "namespace Shop;\n\npublic class Handler {\n"
                              "  public TEvent Handle<[Foo] TEvent>(TEvent e) => e;\n  public TEvent Keep(TEvent e) => e;\n}\n"},
               ""),
    "go": ({"go.mod": "module example.com/shop\n\ngo 1.22\n",
            "ev/tevent.go": "package ev\n\ntype TEvent struct {\n\tID string\n}\n",
            "ev/bus.go": "package ev\n\ntype Bus[TEvent any] struct{}\n\n"
                         "func (b *Bus[TEvent]) Publish(e TEvent) TEvent { return e }\n",
            "ev/handler.go": "package ev\n\nfunc Handle[TEvent any](e TEvent) TEvent { return e }\n\n"
                             "func Keep(e TEvent) TEvent { return e }\n"},
           "ev/"),
    "rust": ({"Cargo.toml": "[package]\nname = \"shop\"\nversion = \"0.1.0\"\n",
              "src/main.rs": "pub struct TEvent { pub id: String }\n\npub struct Bus<TEvent> { e: Option<TEvent> }\n\n"
                             "impl<TEvent> Bus<TEvent> {\n    pub fn publish(&self, e: TEvent) -> TEvent { e }\n}\n\n"
                             "pub fn handle<TEvent>(e: TEvent) -> TEvent { e }\n\n"
                             "pub fn keep(e: TEvent) -> TEvent { e }\n"},
             "src/"),
    "scala": ({"build.sbt": 'lazy val shop = (project in file("shop"))\n',
               "shop/src/main/scala/a/ev/TEvent.scala": "package a.ev\n\nfinal case class TEvent(id: String)\n",
               "shop/src/main/scala/a/ev/Bus.scala": "package a.ev\n\nclass Bus[TEvent] {\n"
                                                     "  def publish(e: TEvent): TEvent = e\n}\n",
               "shop/src/main/scala/a/ev/Handler.scala": "package a.ev\n\nobject Handler {\n"
                                                         "  def handle[TEvent](e: TEvent): TEvent = e\n"
                                                         "  def keep(e: TEvent): TEvent = e\n}\n"},
              "shop/src/main/scala/a/ev/"),
    "python": ({"pyproject.toml": '[project]\nname = "shop"\nversion = "0.1"\n',
                "shop/__init__.py": "",
                "shop/tevent.py": "class TEvent:\n    id: str\n",
                "shop/bus.py": "from shop.tevent import TEvent\n\n\nclass Bus[TEvent]:\n"
                               "    def publish(self, e: TEvent) -> TEvent:\n        return e\n",
                "shop/handler.py": "from shop.tevent import TEvent\n\n\n"
                                   "def handle[TEvent](e: TEvent) -> TEvent:\n    return e\n\n\n"
                                   "def keep(e: TEvent) -> TEvent:\n    return e\n"},
               "shop/"),
}


@pytest.mark.parametrize("lang", sorted(TYPE_PARAM_CASES))
def test_named_type_parameters_never_link_to_a_same_named_class(make_repo, lang):
    files, folder = TYPE_PARAM_CASES[lang]
    s = build(make_repo, files)
    methods = {n["name"].lower(): n for n in s["nodes"] if n["kind"] == "method"}
    tevent = [n["id"] for n in s["nodes"] if n["kind"] == "class" and n["name"] == "TEvent"]
    assert len(tevent) == 1, lang
    for name in ("publish", "handle"):
        sig = methods[name]["signature"]
        assert [p.get("refs", []) for p in sig["params"]] == [[] for _ in sig["params"]], (lang, name)
        assert sig.get("returns_refs", []) == [], (lang, name)
    keep = methods["keep"]["signature"]
    assert [p.get("refs") for p in keep["params"]] == [tevent], lang
    assert keep.get("returns_refs") == tevent, lang


def test_a_repo_package_named_like_a_standard_library_module_still_links(make_repo):
    s = build(make_repo, {
        "pyproject.toml": '[project]\nname = "svc"\nversion = "0.1"\n',
        "email/__init__.py": "",
        "email/sender.py": "class Mailer:\n    host: str\n",
        "svc/__init__.py": "",
        "svc/app.py": "from email import sender\nfrom email.sender import Mailer\n\n\n"
                      "def run(m: sender.Mailer, n: Mailer) -> None:\n    return None\n",
    })
    assert links(s, "run", "svc/app.py") == ([["email/sender.py:Mailer"], ["email/sender.py:Mailer"]], [])
