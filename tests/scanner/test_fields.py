"""Declared fields of data types on class nodes (spec: traces §1.1), one case per language."""
from vizcode import ids
from vizcode.adapters import generic
from vizcode.adapters import python as py
from vizcode.adapters import scala
from vizcode.adapters.langs import SPECS, TSX


def fields_by_name(res) -> dict:
    """Class name -> its `fields` (None when the node has no `fields` key)."""
    return {n["name"]: n.get("fields") for n in res["nodes"] if n["kind"] == "class"}


def f(*pairs):
    return [{"name": n, "type": t} for n, t in pairs]


def fv(*triples):
    """Fields of a language that says visibility by modifiers: (name, type, visibility)."""
    return [{"name": n, "type": t, "visibility": v} for n, t, v in triples]


def test_scala_case_class_parameters_are_fields():
    src = ("package a.b\n\nfinal case class Reservation(id: BayId, at: Long = 0, private val tags: List[String], "
           "`type`: String)"
           "(implicit c: Ctx)\n\nclass Plain(x: Int)\n\ntrait Port\n\nobject Reservation\n")
    mod = {"id": "mod:svc", "path": "svc", "lang": "scala", "build": "sbt"}
    res = scala.parse(src.encode(), "svc/src/main/scala/a/b/R.scala", mod, ids.IdRegistry())
    got = {n["id"]: n.get("fields") for n in res["nodes"] if n["kind"] == "class"}
    # the first parameter list only; a backticked name without its backticks; plain classes and objects have none
    assert got == {"svc::a.b.Reservation": fv(("id", "BayId", "public"), ("at", "Long", "public"),
                                              ("tags", "List[String]", "private"), ("type", "String", "public")),
                   "svc::a.b.Plain": None, "svc::a.b.Port": None, "svc::a.b.Reservation$": None}


def test_scala_implicit_and_using_first_lists_are_not_fields():
    src = "package a\n\ncase class A(implicit c: Ctx)\n\ncase class B(using c: Ctx)\n\ncase class C(x: Int)(using c: Ctx)\n"
    mod = {"id": "mod:svc", "path": "svc", "lang": "scala", "build": "sbt"}
    got = fields_by_name(scala.parse(src.encode(), "svc/src/main/scala/a/A.scala", mod, ids.IdRegistry()))
    assert got == {"A": None, "B": None, "C": fv(("x", "Int", "public"))}


def test_python_class_level_annotated_attributes_are_fields():
    src = ("from dataclasses import dataclass\nfrom typing import ClassVar\n\n\n@dataclass\nclass Quote:\n"
           "    bay: str\n    total: int = 0\n    plain = 5\n    registry: ClassVar[dict] = {}\n    note: \"Note\"\n\n"
           "    def price(self) -> int:\n        self.cache: int = 1\n        return self.total\n\n\n"
           "class Service:\n    def run(self):\n        pass\n")
    mod = {"id": "mod:worker", "path": "worker", "lang": "python", "build": "python-package"}
    got = fields_by_name(py.parse(src.encode(), "worker/quote.py", mod, ids.IdRegistry()))
    # un-annotated and ClassVar attributes are not fields; nor are attributes set inside methods
    assert got == {"Quote": f(("bay", "str"), ("total", "int"), ("note", '"Note"')), "Service": None}


def test_cut_off_scala_and_python_sources_never_raise():
    """A file cut anywhere (a parse error, ERROR nodes inside a class) still parses: a reader that raised would
    drop the whole file from the scan."""
    scala_src = "package a\nfinal case class R(id: BayId, `type`: String)(implicit c: C)\n"
    py_src = "class Quote:\n    bay: str\n    total: int = 0\n    k: ClassVar[int] = 1\n"
    for end in range(1, len(scala_src)):
        scala.parse(scala_src[:end].encode(), "svc/R.scala", {"id": "mod:svc", "path": "svc", "lang": "scala",
                                                              "build": "sbt"}, ids.IdRegistry())
    for end in range(1, len(py_src)):
        py.parse(py_src[:end].encode(), "worker/q.py", {"id": "mod:worker", "path": "worker", "lang": "python",
                                                        "build": "python-package"}, ids.IdRegistry())


def generic_fields(lang: str, src: str, rel: str, spec=None) -> dict:
    mod = {"id": "mod:svc", "path": "svc", "lang": lang, "build": "dir"}
    return fields_by_name(generic.parse(src.encode(), rel, mod, ids.IdRegistry(), spec=spec or SPECS[lang]))


def test_java_record_components_and_non_static_fields():
    src = ("package a;\n\nrecord Charge(String id, List<Long> cents) { static int K = 1; }\n\n"
           "class Order {\n  private final String id;\n  static int COUNT;\n  int a, b;\n  @Id Long pk;\n"
           "  void f() {}\n}\n\ninterface Port { int X = 1; }\n")
    assert generic_fields("java", src, "svc/src/main/java/a/Order.java") == {
        "Charge": fv(("id", "String", "public"), ("cents", "List<Long>", "public")),
        "Order": fv(("id", "String", "private"), ("a", "int", "public"), ("b", "int", "public"), ("pk", "Long", "public")),
        "Port": None}


def test_kotlin_val_var_constructor_parameters_and_properties():
    src = ("package a\n\ndata class Charge(val id: String, var cents: List<Long>, plain: Int, val bay: Bay?) {\n"
           "  val extra: Int = 1\n  var untyped = 2\n  fun f() {}\n}\n\nclass Svc(private val repo: Repo)\n\n"
           "interface Port\n")
    assert generic_fields("kotlin", src, "svc/src/main/kotlin/a/Charge.kt") == {
        "Charge": fv(("id", "String", "public"), ("cents", "List<Long>", "public"), ("bay", "Bay?", "public"),
                     ("extra", "Int", "public"), ("untyped", None, "public")),
        "Svc": fv(("repo", "Repo", "private")),
        "Port": None}


TS_SRC = ("export interface Charge { id: string; cents?: number[]; pay(x: number): void; "
          "readonly byBay: Map<string, Bay> }\n"
          "export type Quote = { bay: Bay; total: number };\n"
          "export type Id = string;\nexport type Status = 'open' | 'paid';\n"
          "export class Svc {\n  private repo: Repo;\n  static K = 1;\n  name = 'x';\n  handle = () => 1;\n"
          "  constructor(private readonly db: Db, other: number) {}\n  run(): void {}\n}\n")


def test_typescript_interface_type_alias_and_class_fields():
    got = generic_fields("typescript", TS_SRC, "svc/src/models.ts")
    # an object type alias is a class node; `type Id = string` is not; a bound arrow function is a method
    assert got == {
        "Charge": f(("id", "string"), ("cents", "number[]"), ("byBay", "Map<string, Bay>")),
        "Quote": f(("bay", "Bay"), ("total", "number")),
        "Svc": f(("repo", "Repo"), ("name", None), ("db", "Db"))}


def test_tsx_reads_fields_like_typescript():
    assert generic_fields("typescript", TS_SRC, "svc/src/models.tsx", spec=TSX)["Quote"] == \
        f(("bay", "Bay"), ("total", "number"))


def test_javascript_class_fields_have_no_type():
    src = "export class A {\n  x = 1;\n  static y = 2;\n  #z;\n  w;\n  f = () => 1;\n  m() {}\n}\n"
    assert generic_fields("javascript", src, "svc/src/a.js") == {"A": f(("x", None), ("#z", None), ("w", None))}


def test_go_struct_fields_and_embedded():
    src = ("package orders\n\ntype Charge struct {\n\tID string `json:\"id\"`\n\tA, B int\n\t*Base\n"
           "\tpay.Money\n\tItems []Item\n}\n\ntype Store interface { Find() }\n\ntype Id string\n")
    assert generic_fields("go", src, "svc/orders/charge.go") == {
        "Charge": f(("ID", "string"), ("A", "int"), ("B", "int"), ("Base", "Base"), ("Money", "pay.Money"),
                    ("Items", "[]Item")),
        "Store": None, "Id": None}


def test_csharp_positional_record_parameters_and_properties():
    src = ("namespace A;\n\npublic record Charge(string Id, List<long> Cents);\n\n"
           "public class Order {\n  public string Id { get; set; }\n  private int _n;\n"
           "  public static int K { get; }\n  public Bay? B { get; init; }\n  int Seen { get; set; }\n  public int F() => 1;\n}\n")
    assert generic_fields("csharp", src, "svc/Order.cs") == {
        "Charge": fv(("Id", "string", "public"), ("Cents", "List<long>", "public")),
        "Order": fv(("Id", "string", "public"), ("B", "Bay?", "public"), ("Seen", "int", "private"))}


def test_rust_named_and_tuple_struct_fields():
    src = ("pub struct Charge { pub id: String, cents: Vec<u64> }\npub struct Pair(pub u32, Bay);\n"
           "struct Unit;\npub enum Kind { A }\npub trait Port {}\n")
    assert generic_fields("rust", src, "svc/src/charge.rs") == {
        "Charge": f(("id", "String"), ("cents", "Vec<u64>")),
        "Pair": f(("0", "u32"), ("1", "Bay")),
        "Unit": None, "Kind": None, "Port": None}


def test_php_typed_properties_and_promoted_constructor_parameters():
    src = ("<?php\nnamespace App\\Billing;\n\nclass Charge {\n  public string $id;\n  private ?Bay $bay = null;\n"
           "  public static int $k = 1;\n  public $untyped;\n"
           "  public function __construct(private readonly Money $total, int $n, protected $loose) {}\n}\n")
    assert generic_fields("php", src, "svc/src/Charge.php") == {
        "Charge": fv(("id", "string", "public"), ("bay", "?Bay", "private"), ("total", "Money", "private"),
                     ("loose", None, "private"))}


def test_ruby_classes_have_no_fields():
    src = ("class Charge\n  attr_accessor :id, :cents\n\n  def initialize(id, cents)\n    @id = id\n  end\nend\n"
           "Point = Struct.new(:x, :y)\n")
    assert generic_fields("ruby", src, "svc/lib/charge.rb") == {"Charge": None}


def test_java_record_varargs_component_is_a_field():
    assert generic_fields("java", "record R(String s, int... xs) {}\n", "svc/R.java") == {
        "R": fv(("s", "String", "public"), ("xs", "int...", "public"))}


def test_go_embedded_generic_field_is_named_by_its_type_without_arguments():
    src = "package a\n\ntype T struct {\n\tGen[int]\n\t*pay.G[a, b]\n}\n"
    assert generic_fields("go", src, "svc/a.go") == {"T": f(("Gen", "Gen[int]"), ("G", "pay.G[a, b]"))}


BROKEN = {"java": ("svc/A.java", "record Charge(String id, List<Long> cents) { static int K = 1; }\n"
                                 "class Order { private final String id; int a, b; void f() {} }\n"),
          "kotlin": ("svc/A.kt", "data class Charge(val id: String, var cents: List<Long>) {\n  val extra: Int = 1\n}\n"),
          "typescript": ("svc/a.ts", TS_SRC),
          "javascript": ("svc/a.js", "class A { x = 1; static y = 2; #z; f = () => 1; m() {} }\n"),
          "go": ("svc/a.go", "package a\ntype Charge struct {\n\tID string `json:\"id\"`\n\tA, B int\n\t*Base\n}\n"),
          "csharp": ("svc/A.cs", "namespace A;\npublic record Charge(string Id);\n"
                                 "public class Order { public string Id { get; set; } }\n"),
          "rust": ("svc/a.rs", "pub struct Charge { pub id: String }\npub struct Pair(pub u32, Bay);\n"),
          "php": ("svc/a.php", "<?php\nclass Charge { public string $id; "
                               "public function __construct(private Money $total) {} }\n")}


def test_cut_off_generic_sources_never_raise():
    """As for Scala and Python: a cut-off file of each walker language parses without raising."""
    for lang, (rel, src) in BROKEN.items():
        for end in range(1, len(src), 3):
            generic_fields(lang, src[:end], rel)
