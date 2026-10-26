from vizcode import ids
from vizcode.scan import structure
from vizcode.scan.adapters import generic
from vizcode.scan.adapters.langs import BY_SUFFIX, SPECS

CSHARP = SPECS["csharp"]
MOD = {"id": "mod:svc", "path": "svc", "lang": "csharp", "build": "dir"}
FILE = "svc/Controllers/OrdersController.cs"
GOLDEN = r"""using System.Linq;
using Json = System.Text.Json;
using static System.Math;
namespace Acme.Orders;

[ApiController]
[Route("api/[controller]")]
public class OrdersController : ControllerBase, IOrders<int>
{
    private readonly IRepo _repo;
    public OrdersController(IRepo repo) { _repo = repo; var m = new Money<int>(0, "EUR"); }

    [HttpGet("{id}")]
    public IActionResult Get(string id, params int[] rest) => Ok(_repo.Find(id));

    private string Url(int a = 1) {
        var u = $"http://pay.example.com/v1/{a}/{rest.Length}";
        var p = @"C:\temp";
        return Environment.GetEnvironmentVariable("DB_URL");
    }
}
public record Money(long Cents, string Cur);
public struct Point { public int X; }
public interface IRepo { Order Find(string id); }
"""
P = "svc::Acme.Orders"
CTRL = f"{P}.OrdersController"


def parse(src: str, rel: str = FILE):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=CSHARP)


def test_csharp_spec_registered():
    assert BY_SUFFIX[".cs"] is CSHARP
    assert CSHARP.grammar == "csharp" and CSHARP.sep == "."
    assert structure.LANGS[".cs"][0] == "csharp"


def test_csharp_nodes():
    res = parse(GOLDEN)
    assert res["package"] == "Acme.Orders"
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        (CTRL, "class", "OrdersController", f"{P}/", 6, "public"),
        (f"{CTRL}#OrdersController/1", "method", "OrdersController", CTRL, 11, "public"),
        (f"{CTRL}#Get/2", "method", "Get", CTRL, 13, "public"),
        (f"{CTRL}#Url/1", "method", "Url", CTRL, 16, "private"),
        (f"{P}.Money", "class", "Money", f"{P}/", 22, "public"),
        (f"{P}.Point", "class", "Point", f"{P}/", 23, "public"),
        (f"{P}.IRepo", "class", "IRepo", f"{P}/", 24, "public"),
        (f"{P}.IRepo#Find/1", "method", "Find", f"{P}.IRepo", 24, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    assert n[f"{CTRL}#OrdersController/1"]["signature"] == {"params": [{"name": "repo", "type": "IRepo"}],
                                                            "returns": None}
    # `params int[] rest` takes any count; a default value is not a type
    assert n[f"{CTRL}#Get/2"]["signature"] == {"params": [{"name": "id", "type": "string"},
                                                          {"name": "*rest", "type": "int[]"}],
                                               "returns": "IActionResult"}
    assert n[f"{CTRL}#Url/1"]["signature"] == {"params": [{"name": "a", "type": "int"}], "returns": "string"}
    assert n[f"{P}.IRepo#Find/1"]["signature"]["returns"] == "Order"
    assert res["supers"] == [(CTRL, ["ControllerBase", "IOrders"])]


def test_csharp_facts():
    res = parse(GOLDEN)
    assert res["imports"] == [
        {"target": "System.Linq", "line": 1, "relative": False, "names": []},
        {"target": "System.Text.Json", "line": 2, "relative": False, "names": []},
        {"target": "System.Math", "line": 3, "relative": False, "names": []},
    ]
    get, url = f"{CTRL}#Get/2", f"{CTRL}#Url/1"
    assert res["calls"] == [
        # `new Money<int>(...)`: the type without its arguments
        {"callee": "Money", "in": f"{CTRL}#OrdersController/1", "line": 11, "args": 2},
        {"callee": "Ok", "in": get, "line": 14, "args": 1},
        {"callee": "_repo.Find", "in": get, "line": 14, "args": 1},
        {"callee": "Environment.GetEnvironmentVariable", "in": url, "line": 19, "args": 1},
    ]
    assert res["strings"] == [
        {"text": "api/[controller]", "line": 7, "in": None},
        {"text": "EUR", "line": 11, "in": f"{CTRL}#OrdersController/1"},
        {"text": "{id}", "line": 13, "in": get},
        {"text": "http://pay.example.com/v1/{a}/{rest.Length}", "line": 17, "in": url},
        {"text": "C:\\temp", "line": 18, "in": url},
        {"text": "DB_URL", "line": 19, "in": url},
    ]
    assert res["env_keys"] == [{"key": "DB_URL", "line": 19}]
    assert res["annotations"] == [
        {"node": CTRL, "text": "[ApiController]", "line": 6},
        {"node": CTRL, "text": '[Route("api/[controller]")]', "line": 7},
        {"node": get, "text": '[HttpGet("{id}")]', "line": 13},
    ]


def test_csharp_block_namespace_and_plain_using():
    res = parse("using System;\nnamespace A.B {\n  class C : I { void F() {} }\n}\n", "svc/C.cs")
    assert res["package"] == "A.B"
    assert [n["id"] for n in res["nodes"]] == ["svc::A.B.C", "svc::A.B.C#F/0"]
    assert res["imports"] == [{"target": "System", "line": 1, "relative": False, "names": []}]
    assert res["supers"] == [("svc::A.B.C", ["I"])]
    # C# defaults: a member without an access modifier is private; a top-level type stays public on the map
    assert [n["visibility"] for n in res["nodes"]] == ["public", "private"]


def test_csharp_non_ascii():
    res = parse('class Café { string Grüß() => "Größe"; }\n', "svc/K.cs")
    assert [n["id"] for n in res["nodes"]] == ["svc::Café", "svc::Café#Grüß/0"]
    assert res["strings"] == [{"text": "Größe", "line": 1, "in": "svc::Café#Grüß/0"}]


def test_csharp_survives_broken_file():
    src = "namespace A;\nclass Ok { void Fine() { Go(); } }\nclass Broken {\n  void Half(int x) {\n    Call(\n"
    res = parse(src, "svc/B.cs")
    assert res["parse_error"] is True
    assert [n["id"] for n in res["nodes"]][:2] == ["svc::A.Ok", "svc::A.Ok#Fine/0"]
    assert {"callee": "Go", "in": "svc::A.Ok#Fine/0", "line": 2, "args": 0} in res["calls"]


def test_csharp_end_to_end(make_repo):
    repo = make_repo({"Api/Controllers/OrdersController.cs": GOLDEN})
    s = structure.build(repo)
    f = "Api/Controllers/OrdersController.cs"
    assert s["files"][f]["lang"] == "csharp"
    assert [e["key"] for e in s["facts"][f]["env_keys"]] == ["DB_URL"]
    # facts.URL stops at an interpolation, as for Scala
    assert [u["url"] for u in s["facts"][f]["urls"]] == ["http://pay.example.com/v1/"]


def test_supers_link_within_one_language(make_repo):
    """`implements` from a class's supers: the C# base class, never the TypeScript interface of the same name."""
    repo = make_repo({"Api/Orders.cs": GOLDEN,
                      "Api/Base.cs": "namespace Acme.Orders;\npublic class ControllerBase { }\n",
                      "web/src/orders.ts": "export interface IOrders {}\n"})
    s = structure.build(repo)
    ctrl = next(n for n in s["nodes"] if n["id"] == "Api::Acme.Orders.OrdersController")
    assert ctrl["implements"] == ["Api::Acme.Orders.ControllerBase"]
