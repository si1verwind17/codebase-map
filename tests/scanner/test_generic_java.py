import dataclasses
import re

from vizcode import ids, stack, structure
from vizcode.adapters import generic
from vizcode.adapters.langs import BY_SUFFIX, SPECS

JAVA = SPECS["java"]
MOD = {"id": "mod:svc", "path": "svc", "lang": "java", "build": "dir"}
FILE = "svc/src/main/java/com/acme/orders/OrderController.java"
GOLDEN = """package com.acme.orders;

import org.springframework.web.bind.annotation.GetMapping;
import java.util.*;
import static org.junit.Assert.assertEquals;

@RestController
public class OrderController {
    private final OrderRepo repo;

    public OrderController(OrderRepo repo) {
        this.repo = repo;
        Money m = new Money(0, "EUR");
    }

    @GetMapping("/{id}")
    public Order find(String id) {
        return repo.find(id).map(x -> x);
    }

    private String url(int a, String... rest) {
        String u = "http://pay.example.com/v1";
        return System.getenv("DB_URL");
    }

    static class Inner {
        void run() {}
    }
}

interface OrderRepo {
    Optional<Order> find(String id);
}

enum Status { OPEN, CLOSED; Status() {} }

record Money(long cents, String cur) { }
"""
P = "svc::com.acme.orders"
CTRL = f"{P}.OrderController"


def parse(src: str, rel: str = FILE, spec=JAVA):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=spec)


def test_java_spec_registered():
    assert BY_SUFFIX[".java"] is JAVA
    assert JAVA.lang == "java" and JAVA.grammar == "java" and JAVA.sep == "."
    assert structure.LANGS[".java"][0] == "java"


def test_java_nodes():
    res = parse(GOLDEN)
    assert res["package"] == "com.acme.orders"
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        (CTRL, "class", "OrderController", f"{P}/", 7, "public"),
        (f"{CTRL}#OrderController/1", "method", "OrderController", CTRL, 11, "public"),
        (f"{CTRL}#find/1", "method", "find", CTRL, 16, "public"),
        (f"{CTRL}#url/2", "method", "url", CTRL, 21, "private"),
        (f"{CTRL}.Inner", "class", "Inner", CTRL, 26, "public"),
        (f"{CTRL}.Inner#run/0", "method", "run", f"{CTRL}.Inner", 27, "public"),
        (f"{P}.OrderRepo", "class", "OrderRepo", f"{P}/", 31, "public"),
        (f"{P}.OrderRepo#find/1", "method", "find", f"{P}.OrderRepo", 32, "public"),
        (f"{P}.Status", "class", "Status", f"{P}/", 35, "public"),
        (f"{P}.Status#Status/0", "method", "Status", f"{P}.Status", 35, "public"),
        (f"{P}.Money", "class", "Money", f"{P}/", 37, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    assert all(x["lang"] == "java" and x["file"] == FILE for x in res["nodes"])
    assert n[CTRL]["metrics"] == {"loc": 23, "methods": 3}
    assert n[f"{CTRL}#OrderController/1"]["signature"] == {"params": [{"name": "repo", "type": "OrderRepo"}],
                                                           "returns": None}
    assert n[f"{CTRL}#find/1"]["signature"] == {"params": [{"name": "id", "type": "String"}], "returns": "Order"}
    # a variadic parameter takes any count, as Python's *args
    assert n[f"{CTRL}#url/2"]["signature"] == {"params": [{"name": "a", "type": "int"},
                                                          {"name": "*rest", "type": "String"}],
                                               "returns": "String"}
    assert n[f"{P}.OrderRepo#find/1"]["signature"]["returns"] == "Optional<Order>"


def test_java_facts():
    res = parse(GOLDEN)
    assert res["imports"] == [
        {"target": "org.springframework.web.bind.annotation", "line": 3, "relative": False, "names": ["GetMapping"]},
        {"target": "java.util", "line": 4, "relative": False, "names": []},
        {"target": "org.junit.Assert", "line": 5, "relative": False, "names": ["assertEquals"]},
    ]
    assert res["calls"] == [
        {"callee": "Money", "in": f"{CTRL}#OrderController/1", "line": 13, "args": 2},
        {"callee": "repo.find(id).map", "in": f"{CTRL}#find/1", "line": 18, "args": 1},
        {"callee": "repo.find", "in": f"{CTRL}#find/1", "line": 18, "args": 1},
        {"callee": "System.getenv", "in": f"{CTRL}#url/2", "line": 23, "args": 1},
    ]
    assert res["strings"] == [
        {"text": "EUR", "line": 13, "in": f"{CTRL}#OrderController/1"},
        {"text": "/{id}", "line": 16, "in": f"{CTRL}#find/1"},
        {"text": "http://pay.example.com/v1", "line": 22, "in": f"{CTRL}#url/2"},
        {"text": "DB_URL", "line": 23, "in": f"{CTRL}#url/2"},
    ]
    assert res["env_keys"] == [{"key": "DB_URL", "line": 23}]
    assert res["annotations"] == [
        {"node": CTRL, "text": "@RestController", "line": 7},
        {"node": f"{CTRL}#find/1", "text": '@GetMapping("/{id}")', "line": 16},
    ]
    assert res["routes"] == []


def test_java_top_level_and_default_package():
    """No package: `_root_`, as Scala. A text block is a string; a class inside a method is not a node."""
    src = ('class A {\n  void f() {\n    class Local { void g() { h(); } }\n'
           '    String q = """\n      SELECT 1\n      """;\n  }\n}\n')
    res = parse(src, "svc/A.java")
    assert res["package"] == "_root_"
    assert [n["id"] for n in res["nodes"]] == ["svc::A", "svc::A#f/0"]
    assert res["calls"] == [{"callee": "h", "in": "svc::A#f/0", "line": 3, "args": 0}]
    assert res["strings"][0]["text"].strip() == "SELECT 1"


def test_generic_survives_broken_file():
    src = "package a.b;\n\npublic class Ok { void fine() { go(); } }\n\npublic class Broken {\n    void half(int x) {\n        call(\n"
    res = parse(src, "svc/Broken.java")
    assert res["parse_error"] is True
    ids_ = [n["id"] for n in res["nodes"]]
    assert ids_[:2] == ["svc::a.b.Ok", "svc::a.b.Ok#fine/0"]
    assert {"callee": "go", "in": "svc::a.b.Ok#fine/0", "line": 3, "args": 0} in res["calls"]


def test_generic_survives_deep_nesting():
    """A long expression nests the tree deeper than Python's recursion limit: the walk is iterative."""
    src = "class A { String f() { return " + " + ".join(['"x"'] * 3000) + "; } }\n"
    res = parse(src, "svc/A.java")
    assert len(res["strings"]) == 3000


def test_generic_dir_package():
    """`package: "dir"`: the folder relative to the module names the package (Go, TS, JS ...)."""
    spec = dataclasses.replace(JAVA, package="dir")
    res = parse("class A { void f() {} }\n", "svc/src/orders/A.java", spec)
    assert res["package"] == "src/orders"
    assert parse("class A {}\n", "svc/A.java", spec)["package"] == "_root_"


def test_java_spans_feed_pattern_routes():
    pat = stack.RoutePattern("java", "spring-get", re.compile(r'@GetMapping\("(?P<path>[^"]+)"\)'),
                             "literal", None, "GET", "stack.yaml")
    res = parse(GOLDEN)
    got = structure._pattern_routes(stack.Stack(patterns=[pat]), "java", GOLDEN.encode(), res, MOD, [])
    assert [(r["method"], r["path"], r["handler"], r["line"]) for r in got] == [("GET", "/{id}", f"{CTRL}#find/1", 16)]


def test_java_end_to_end(make_repo):
    repo = make_repo({
        "src/main/java/com/acme/orders/OrderController.java": GOLDEN,
        "src/main/java/com/acme/orders/OrderService.java":
            "package com.acme.orders;\n\nclass OrderService {\n  void place() { new OrderController(null); }\n}\n",
        "src/test/java/com/acme/orders/OrderControllerTest.java": "package com.acme.orders;\nclass OrderControllerTest {}\n",
    })
    s = structure.build(repo)
    assert s["modules"] == [{"id": "mod:src", "path": "src", "lang": "java", "build": "dir"}]
    f = "src/main/java/com/acme/orders/OrderController.java"
    assert set(s["files"]) == {f, "src/main/java/com/acme/orders/OrderService.java"}
    assert s["files"][f] == {"lang": "java", "module": "mod:src", "node": "src::com.acme.orders.OrderController",
                             "parse_error": False}
    pkg = next(n for n in s["nodes"] if n["kind"] == "package")
    assert (pkg["id"], pkg["parent"], pkg["lang"]) == ("src::com.acme.orders/", "mod:src", "java")
    assert [e["key"] for e in s["facts"][f]["env_keys"]] == ["DB_URL"]
    assert [u["url"] for u in s["facts"][f]["urls"]] == ["http://pay.example.com/v1"]
    assert "names" not in s["facts"][f]["imports"][0]
    assert [r for r in s["relations"] if r["kind"] == "uses-code"] == []
    md = structure.summary_md(s)
    assert "## mod:src (java, dir, 2 files)" in md


def test_java_supers_and_generic_new():
    """What a class extends or implements, without type arguments; `new X<T>()` calls `X`."""
    src = ("class A extends B<X> implements C, d.E<Y> { void f() { new X<T>(); } }\n"
           "interface I extends J, K {}\nenum S implements I { A }\nrecord R(int x) implements I {}\n")
    res = parse(src, "svc/A.java")
    assert res["supers"] == [("svc::A", ["B", "C", "d.E"]), ("svc::I", ["J", "K"]), ("svc::S", ["I"]),
                             ("svc::R", ["I"])]
    assert res["calls"] == [{"callee": "X", "in": "svc::A#f/0", "line": 1, "args": 0}]


def test_supers_link_across_the_jvm_family(make_repo):
    """A Scala class may implement a Java interface (one family: Java, Kotlin, Scala)."""
    repo = make_repo({"svc/src/main/java/com/acme/Api.java": "package com.acme;\npublic interface Api { }\n",
                      "svc/src/main/scala/com/acme/Impl.scala": "package com.acme\n\nclass Impl extends Api\n"})
    s = structure.build(repo)
    impl = next(n for n in s["nodes"] if n["kind"] == "class" and n["name"] == "Impl")
    api = next(n for n in s["nodes"] if n["kind"] == "class" and n["name"] == "Api")
    assert impl["implements"] == [api["id"]]
