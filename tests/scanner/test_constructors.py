"""`ctor` on class nodes: the method that builds the class (a constructor, `__init__`, a Go `New...` factory),
or the class's own parameter list (Scala class parameters, a Kotlin primary constructor)."""
import copy

from vizcode import mapcheck, structure
from vizcode.assemble import assemble


def build(make_repo, files: dict[str, str]) -> dict:
    return structure.build(make_repo(files), "docs/viz-code")


def node(s: dict, kind: str, name: str, file: str | None = None) -> dict:
    hits = [n for n in s["nodes"] if n["kind"] == kind and n["name"] == name and file in (None, n["file"])]
    assert len(hits) == 1, [n["id"] for n in hits]
    return hits[0]


def ctor(s: dict, name: str, file: str | None = None) -> dict | None:
    return node(s, "class", name, file).get("ctor")


def test_python_init(make_repo):
    s = build(make_repo, {
        "shop/__init__.py": "",
        "shop/repo.py": "class OrderRepo:\n    pass\n",
        "shop/service.py": "from shop.repo import OrderRepo\n\n\nclass OrderService:\n"
                           "    def __init__(self, repo: OrderRepo, clock: Clock):\n        self.repo = repo\n",
    })
    init = node(s, "method", "__init__")
    assert init["id"].endswith("#__init__/2")
    assert ctor(s, "OrderService") == {"method": init["id"]}
    repo, clock = init["signature"]["params"]
    assert repo["refs"] == [node(s, "class", "OrderRepo")["id"]] and "refs" not in clock
    assert ctor(s, "OrderRepo") is None


def test_java_overloads(make_repo):
    s = build(make_repo, {
        "pom.xml": "<project><artifactId>shop</artifactId></project>\n",
        "src/main/java/shop/OrderService.java":
            "package shop;\n\npublic class OrderService {\n"
            "    public OrderService(OrderRepo repo) { this(repo, null, 3); }\n"
            "    public OrderService(OrderRepo repo, Clock clock, int limit) {}\n"
            "    public void place(Order o) {}\n}\n",
    })
    got = ctor(s, "OrderService")
    assert got["method"].endswith("OrderService#OrderService/3") and got["of"] == 2 and len(got) == 2


def test_records_have_none(make_repo):
    s = build(make_repo, {
        "pom.xml": "<project><artifactId>shop</artifactId></project>\n",
        "src/main/java/shop/Money.java": "package shop;\n\npublic record Money(long cents, String cur) {\n"
                                         "    public Money { if (cents < 0) throw new IllegalStateException(); }\n}\n",
        "src/main/java/shop/Line.java": "package shop;\n\npublic record Line(String sku, int n) {\n"
                                        "    public Line(String sku, int n) { this.sku = sku; this.n = n; }\n"
                                        "    public Line(String sku) { this(sku, 1); }\n}\n",
        "Shop.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
        "Quote.cs": "namespace Shop;\n\npublic record Quote(long Total) {\n"
                    "    public Quote(int n, int m) : this(n) {}\n}\n\n"
                    "public record struct Bay(int N) {\n    public Bay(string s) : this(1) {}\n}\n",
    })
    assert [ctor(s, n) for n in ("Money", "Line", "Quote", "Bay")] == [None] * 4


def test_go_factory_pointer_tuple(make_repo):
    s = build(make_repo, {
        "go.mod": "module example.com/shop\n\ngo 1.22\n",
        "store/store.go": "package store\n\nimport \"database/sql\"\n\ntype Store struct {\n\tdb *sql.DB\n}\n\n"
                          "func NewStore(db *sql.DB) (*Store, error) {\n\treturn &Store{db: db}, nil\n}\n",
        "other/other.go": "package other\n\ntype Store struct{}\n\ntype Other struct{}\n\n"
                          "func NewOther() *Other {\n\treturn &Other{}\n}\n",
    })
    factory = node(s, "method", "NewStore")
    assert factory["id"] == node(s, "file", "store.go")["id"] + "#NewStore/1"
    assert ctor(s, "Store", "store/store.go") == {"method": factory["id"]}
    assert ctor(s, "Store", "other/other.go") is None
    assert ctor(s, "Other") == {"method": node(s, "method", "NewOther")["id"]}


def test_go_factory_skips_interfaces_and_collections(make_repo):
    s = build(make_repo, {
        "go.mod": "module example.com/shop\n\ngo 1.22\n",
        "orders/orders.go": "package orders\n\ntype Repo interface {\n\tFind(id string) string\n}\n\n"
                            "type Service interface {\n\tPlace(id string) error\n}\n\n"
                            "type service struct {\n\trepo Repo\n}\n\n"
                            "func (s *service) Place(id string) error {\n\treturn nil\n}\n\n"
                            "func NewService(r Repo) Service {\n\treturn &service{repo: r}\n}\n\n"
                            "func NewServices() []*service {\n\treturn nil\n}\n\n"
                            "func NewIndex() map[string]*service {\n\treturn nil\n}\n",
        "web/web.go": "package web\n\nimport \"net/http\"\n\ntype Handler struct{}\n\ntype Client struct{}\n\n"
                      "func NewMux(n int) http.Handler {\n\treturn nil\n}\n\n"
                      "func NewClient(n int) (*http.Client, error) {\n\treturn nil, nil\n}\n",
    })
    assert ctor(s, "Service") is None and ctor(s, "service") is None
    assert ctor(s, "Handler") is None and ctor(s, "Client") is None      # another package's type, of the same name


def test_rust_new(make_repo):
    s = build(make_repo, {
        "Cargo.toml": "[package]\nname = \"shop\"\nversion = \"0.1.0\"\n",
        "src/main.rs": "pub struct Orders { n: u32 }\n\nimpl Orders {\n"
                       "    pub fn new(n: u32) -> Self { Orders { n } }\n    pub fn len(&self) -> u32 { self.n }\n}\n",
    })
    assert ctor(s, "Orders") == {"method": node(s, "method", "new")["id"]}


def test_ts_constructor(make_repo):
    s = build(make_repo, {
        "package.json": '{"name": "web"}\n',
        "src/orders.ts": "export class Orders {\n  constructor(private repo: Repo) {}\n  list(): string[] { return []; }\n}\n",
    })
    assert ctor(s, "Orders") == {"method": node(s, "method", "constructor")["id"]}


def test_php_construct(make_repo):
    s = build(make_repo, {
        "composer.json": '{"name": "acme/shop"}\n',
        "src/Orders.php": "<?php\nnamespace App;\n\nclass Orders {\n"
                          "    public function __construct(Repo $repo) {}\n    public function list() {}\n}\n",
    })
    assert ctor(s, "Orders") == {"method": node(s, "method", "__construct")["id"]}


def test_ruby_initialize(make_repo):
    s = build(make_repo, {
        "Gemfile": "source 'https://rubygems.org'\n",
        "lib/orders.rb": "class Orders\n  def initialize(repo)\n    @repo = repo\n  end\nend\n",
    })
    assert ctor(s, "Orders") == {"method": node(s, "method", "initialize")["id"]}


def test_csharp_ctor(make_repo):
    s = build(make_repo, {
        "Shop.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
        "Orders.cs": "namespace Shop;\n\npublic class Orders {\n    public Orders(IRepo repo) {}\n"
                     "    public void List() {}\n}\n\npublic class Ledger(IRepo repo) { }\n",
    })
    assert ctor(s, "Orders") == {"method": node(s, "method", "Orders")["id"]}
    assert ctor(s, "Ledger") is None                   # a primary constructor is not read


def test_csharp_static_ctor_is_not_one(make_repo):
    s = build(make_repo, {
        "Shop.csproj": "<Project Sdk=\"Microsoft.NET.Sdk\"></Project>\n",
        "Orders.cs": "namespace Shop;\n\npublic class Orders {\n    static Orders() {}\n"
                     "    public Orders(IRepo repo) {}\n}\n\npublic class Clock {\n    static Clock() {}\n}\n",
    })
    assert ctor(s, "Orders") == {"method": node(s, "class", "Orders")["id"] + "#Orders/1"}
    assert ctor(s, "Clock") is None


def test_java_enum_has_none(make_repo):
    s = build(make_repo, {
        "pom.xml": "<project><artifactId>shop</artifactId></project>\n",
        "src/main/java/shop/Status.java": "package shop;\n\npublic enum Status {\n    OPEN(1), PAID(2);\n\n"
                                          "    private final int code;\n\n"
                                          "    Status(int code) { this.code = code; }\n}\n",
    })
    assert ctor(s, "Status") is None


def test_scala_class_params(make_repo):
    s = build(make_repo, {
        "build.sbt": 'lazy val app = (project in file("."))\n',
        "src/main/scala/shop/Live.scala": "class Live(repo: InvoiceRepo, n: Int) extends Billing\n",
        "src/main/scala/shop/Repo.scala": "package shop\n\ntrait InvoiceRepo\ntrait Billing\n"
                                          "case class Order(lines: List[Line])\ncase class Line(n: Int)\n",
    })
    assert ctor(s, "Live") == {"params": [{"name": "repo", "type": "InvoiceRepo",
                                           "refs": [node(s, "class", "InvoiceRepo")["id"]]},
                                          {"name": "n", "type": "Int"}], "line": 1}
    assert ctor(s, "Order") is None


def test_kotlin_primary(make_repo):
    s = build(make_repo, {
        "build.gradle.kts": "",
        "src/main/kotlin/shop/Orders.kt": "package shop\n\ninterface OrderRepo\n\ndata class Order(val id: String)\n\n"
                                          "class OrderService(private val repo: OrderRepo, limit: Int)\n",
    })
    assert ctor(s, "OrderService") == {"params": [{"name": "repo", "type": "OrderRepo",
                                                   "refs": [node(s, "class", "OrderRepo")["id"]]},
                                                  {"name": "limit", "type": "Int"}], "line": 7}
    assert ctor(s, "Order") is None


def test_schema_accepts_constructor(make_repo):
    cmap = assemble(build(make_repo, {
        "build.sbt": 'lazy val app = (project in file("."))\n',
        "src/main/scala/shop/Live.scala": "package shop\n\ntrait InvoiceRepo\n\nclass Live(repo: InvoiceRepo)\n",
        "shop/__init__.py": "",
        "shop/a.py": "class A:\n    def __init__(self, n: int):\n        self.n = n\n",
    }), {})
    shapes = {tuple(sorted(n["ctor"])) for n in cmap["nodes"] if "ctor" in n}
    assert {("method",), ("line", "params")} <= shapes
    assert mapcheck.check(cmap) == []
    i = next(k for k, n in enumerate(cmap["nodes"]) if "ctor" in n)
    for value in ({"method": "x", "of": 1},                       # `of` only when there are several
                  {"method": "x", "line": 3},
                  {"method": "x", "params": [], "line": 1},       # one shape or the other
                  {"params": [], "line": 1, "of": 2},
                  {"params": [{"name": "n"}], "line": 1},         # type is required (null when none)
                  {"method": "x", "x": 1}):
        bad = copy.deepcopy(cmap)
        bad["nodes"][i]["ctor"] = value
        assert any(e.startswith("schema: nodes/") for e in mapcheck.check(bad)), value
