from vizcode import ids, structure
from vizcode.adapters import generic
from vizcode.adapters.langs import BY_SUFFIX, SPECS

KOTLIN = SPECS["kotlin"]
MOD = {"id": "mod:svc", "path": "svc", "lang": "kotlin", "build": "dir"}
FILE = "svc/src/main/kotlin/com/acme/orders/Routes.kt"
GOLDEN = """package com.acme.orders

import io.ktor.server.routing.*
import io.ktor.server.routing.get as g
import java.util.UUID

@Serializable
data class Order(val id: String, val total: Long = 0) : Base(), Comparable<Order>

interface OrderRepo {
    suspend fun find(id: String): Order?
}

object Registry {
    private fun url(a: Int, vararg rest: String): String {
        val u = "http://pay.example.com/v1/$a/${rest.size}"
        return System.getenv("DB_URL") ?: "none"
    }
}

class OrderService(private val repo: OrderRepo) : OrderApi {
    suspend fun `place order`(id: String) = repo.find(id)?.let { it }
    fun make(): List<Order> = listOf(Order("x"))
}

fun Route.orders() {
    get("/orders/{id}") { call.respond(repo.find(call.parameters["id"]!!)) }
}
"""
P = "svc::com.acme.orders"
SVC = f"{P}.OrderService"
FILE_ID = f"{P}/Routes.kt"


def parse(src: str, rel: str = FILE):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=KOTLIN)


def test_kotlin_spec_registered():
    assert BY_SUFFIX[".kt"] is KOTLIN and BY_SUFFIX[".kts"] is KOTLIN
    assert KOTLIN.grammar == "kotlin" and KOTLIN.sep == "."
    assert structure.LANGS[".kt"][0] == "kotlin"


def test_kotlin_nodes():
    res = parse(GOLDEN)
    assert res["package"] == "com.acme.orders"
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        (f"{P}.Order", "class", "Order", f"{P}/", 7, "public"),
        (f"{P}.OrderRepo", "class", "OrderRepo", f"{P}/", 10, "public"),
        (f"{P}.OrderRepo#find/1", "method", "find", f"{P}.OrderRepo", 11, "public"),
        (f"{P}.Registry", "class", "Registry", f"{P}/", 14, "public"),
        (f"{P}.Registry#url/2", "method", "url", f"{P}.Registry", 15, "private"),
        (SVC, "class", "OrderService", f"{P}/", 21, "public"),
        # a backtick name loses its backticks
        (f"{SVC}#place order/1", "method", "place order", SVC, 22, "public"),
        (f"{SVC}#make/0", "method", "make", SVC, 23, "public"),
        # an extension function is named without its receiver and belongs to the file
        (FILE_ID, "file", "Routes.kt", f"{P}/", 1, "public"),
        (f"{FILE_ID}#orders/0", "method", "orders", FILE_ID, 26, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    assert n[f"{P}.OrderRepo#find/1"]["signature"] == {"params": [{"name": "id", "type": "String"}],
                                                       "returns": "Order?"}
    assert n[f"{P}.Registry#url/2"]["signature"] == {"params": [{"name": "a", "type": "Int"},
                                                               {"name": "*rest", "type": "String"}],
                                                    "returns": "String"}
    assert n[f"{SVC}#place order/1"]["signature"]["returns"] is None
    assert n[f"{SVC}#make/0"]["signature"] == {"params": [], "returns": "List<Order>"}
    assert n[FILE_ID]["metrics"]["methods"] == 1
    assert res["supers"] == [(f"{P}.Order", ["Base", "Comparable"]), (SVC, ["OrderApi"])]


def test_kotlin_facts():
    res = parse(GOLDEN)
    assert res["imports"] == [
        {"target": "io.ktor.server.routing", "line": 3, "relative": False, "names": []},
        {"target": "io.ktor.server.routing", "line": 4, "relative": False, "names": ["get"]},
        {"target": "java.util", "line": 5, "relative": False, "names": ["UUID"]},
    ]
    url, place, make, orders = (f"{P}.Registry#url/2", f"{SVC}#place order/1", f"{SVC}#make/0",
                                 f"{FILE_ID}#orders/0")
    assert res["calls"] == [
        {"callee": "System.getenv", "in": url, "line": 17, "args": 1},
        # a call with only a trailing lambda has no argument list: count unknown
        {"callee": "repo.find(id)?.let", "in": place, "line": 22, "args": None},
        {"callee": "repo.find", "in": place, "line": 22, "args": 1},
        {"callee": "listOf", "in": make, "line": 23, "args": 1},
        {"callee": "Order", "in": make, "line": 23, "args": 1},
        {"callee": "get", "in": orders, "line": 27, "args": 1},
        {"callee": "call.respond", "in": orders, "line": 27, "args": 1},
        {"callee": "repo.find", "in": orders, "line": 27, "args": 1},
    ]
    assert res["strings"] == [
        {"text": "http://pay.example.com/v1/{a}/{rest.size}", "line": 16, "in": url},
        {"text": "DB_URL", "line": 17, "in": url},
        {"text": "none", "line": 17, "in": url},
        {"text": "x", "line": 23, "in": make},
        {"text": "/orders/{id}", "line": 27, "in": orders},
        {"text": "id", "line": 27, "in": orders},
    ]
    assert res["env_keys"] == [{"key": "DB_URL", "line": 17}]
    assert res["annotations"] == [{"node": f"{P}.Order", "text": "@Serializable", "line": 7}]


def test_kotlin_splat_and_raw_string():
    src = 'fun f(xs: IntArray) = g(*xs)\nval q = """\n  SELECT $x\n"""\n'
    res = parse(src, "svc/F.kt")
    assert res["package"] == "_root_"
    assert res["calls"] == [{"callee": "g", "in": "svc::_root_/F.kt#f/1", "line": 1, "args": None}]
    assert res["strings"] == [{"text": "\n  SELECT {x}\n", "line": 2, "in": None}]


def test_kotlin_non_ascii():
    res = parse('package é.ü\n\nfun grüße(name: String) = "Grüße, $name"\n', "svc/G.kt")
    assert res["package"] == "é.ü"
    assert [n["id"] for n in res["nodes"]] == ["svc::é.ü/G.kt", "svc::é.ü/G.kt#grüße/1"]
    assert res["strings"] == [{"text": "Grüße, {name}", "line": 3, "in": "svc::é.ü/G.kt#grüße/1"}]


def test_kotlin_survives_broken_file():
    src = "package a\n\nclass Ok { fun fine() { go() } }\n\nclass Broken {\n    fun half(x: Int) {\n        call(\n"
    res = parse(src, "svc/B.kt")
    assert res["parse_error"] is True
    assert [n["id"] for n in res["nodes"]][:2] == ["svc::a.Ok", "svc::a.Ok#fine/0"]
    assert {"callee": "go", "in": "svc::a.Ok#fine/0", "line": 3, "args": 0} in res["calls"]


def test_kotlin_end_to_end(make_repo):
    repo = make_repo({"src/main/kotlin/com/acme/orders/Routes.kt": GOLDEN})
    s = structure.build(repo)
    f = "src/main/kotlin/com/acme/orders/Routes.kt"
    assert s["files"][f]["lang"] == "kotlin"
    assert s["modules"] == [{"id": "mod:src", "path": "src", "lang": "kotlin", "build": "dir"}]
    assert [e["key"] for e in s["facts"][f]["env_keys"]] == ["DB_URL"]
