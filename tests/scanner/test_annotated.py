"""The annotated route form of stack.yaml: parse_annotation, annotated_routes, validation, Stack report."""
import pytest
from conftest import with_stack

from vizcode import stack, structure

from helpers import write

# the stack.yaml mechanism alone: the packs' own routes and tables (Spring, JAX-RS, JPA, Quill, SQLAlchemy)
# would match these fixtures too
pytestmark = pytest.mark.usefixtures("packs_without_patterns")

SPRING = ("java:\n  routes:\n    - name: spring-mvc\n      form: annotated\n"
          "      when: org.springframework.web.bind.annotation\n      prefix: [RequestMapping]\n"
          "      verbs: {GetMapping: GET, PostMapping: POST, PutMapping: PUT, DeleteMapping: DELETE, PatchMapping: PATCH,\n"
          "              RequestMapping: from-method-arg}\n      path_args: [value, path, 0]\n")
JAXRS = ("java:\n  routes:\n    - name: jax-rs\n      form: annotated\n      when: jakarta.ws.rs\n      prefix: [Path]\n"
         "      verbs: {GET: GET, POST: POST, DELETE: DELETE}\n      method_path: [Path]\n")
NEST = ("typescript:\n  routes:\n    - name: nestjs\n      form: annotated\n      when: '@nestjs/common'\n"
        "      prefix: [Controller]\n      verbs: {Get: GET, Post: POST, Delete: DELETE}\n")
ASPNET = ("csharp:\n  routes:\n    - name: aspnet\n      form: annotated\n      when: Microsoft.AspNetCore.Mvc\n"
          "      prefix: [Route]\n      verbs: {HttpGet: GET, HttpPost: POST, HttpDelete: DELETE}\n"
          "      path_args: [Template, 0]\n      token: {'[controller]': class-stem, '[action]': method-name}\n")

SPRING_SRC = {
    "pom.xml": "<project><artifactId>shop</artifactId></project>\n",
    "src/main/java/io/demo/shop/OrderController.java":
        "package io.demo.shop;\n\n"
        "import org.springframework.web.bind.annotation.*;\n\n"
        "@RestController\n"
        "@RequestMapping({\"/orders/\", \"/v1/orders\"})\n"
        "public class OrderController {\n"
        "  @GetMapping(\"/{id}\")\n"
        "  public String get(@PathVariable String id) { return id; }\n"
        "  @PostMapping\n"
        "  public void create() {}\n"
        "  @GetMapping(value = {\"/a\", \"b\"}, produces = \"application/json\")\n"
        "  public void two() {}\n"
        "  @RequestMapping(path = \"/m\", method = {RequestMethod.PUT, RequestMethod.PATCH})\n"
        "  public void viaArg() {}\n"
        "  @RequestMapping(\"/any\")\n"
        "  public void any() {}\n"
        "  @GetMapping(PATH)\n"
        "  public void constant() {}\n"
        "  @org.springframework.web.bind.annotation.DeleteMapping(path = \"/{id}\")\n"
        "  public void remove() {}\n"
        "  public void plain() {}\n"
        "}\n",
    "src/main/java/io/demo/shop/Health.java":
        "package io.demo.shop;\n\nimport org.springframework.web.bind.annotation.GetMapping;\n\n"
        "public class Health {\n  @GetMapping(\"/health\")\n  public String health() { return \"ok\"; }\n}\n",
    "src/main/java/io/demo/shop/Empty.java":
        "package io.demo.shop;\n\nimport org.springframework.web.bind.annotation.RequestMapping;\n\n"
        "@RequestMapping(\"/empty\")\npublic class Empty {\n  public void nothing() {}\n}\n",
    "src/main/java/io/demo/shop/NoImport.java":
        "package io.demo.shop;\n\npublic class NoImport {\n  @GetMapping(\"/x\")\n  public void x() {}\n}\n",
}
CTRL = "io.demo.shop.OrderController"


def routes_of(s, f):
    """(method, path, handler without its module, line) of a file's routes."""
    return [(r["method"], r["path"], r["handler"].split("::", 1)[1], r["line"]) for r in s["facts"][f]["routes"]]


# parse_annotation

@pytest.mark.parametrize("text,expect", [
    ('@GetMapping(value={"/a","/b"})', ("GetMapping", [], {"value": ["/a", "/b"]})),
    ('[HttpGet("{id}")]', ("HttpGet", [["{id}"]], {})),
    ("@Get(':id')", ("Get", [[":id"]], {})),
    ("@Controller", ("Controller", [], {})),
    ("@Controller()", ("Controller", [], {})),
    ("@org.x.GetMapping(\"/a\")", ("GetMapping", [["/a"]], {})),
    ("@GetMapping(PATH)", ("GetMapping", [[]], {})),
    ("@Get(`${base}/x`)", ("Get", [[]], {})),
    ("@Get(`/plain`)", ("Get", [["/plain"]], {})),
    ('@GetMapping("/a" + "/b")', ("GetMapping", [[]], {})),
    ('@GetMapping({"/a", B})', ("GetMapping", [[]], {})),
    ('@GetMapping(["/k"])', ("GetMapping", [["/k"]], {})),
    ('@GetMapping(arrayOf("/k"))', ("GetMapping", [["/k"]], {})),
    ('@RequestMapping(value = ["/z"], method = [RequestMethod.GET])',
     ("RequestMapping", [], {"value": ["/z"], "method": []})),
    ('[method: HttpPost(Name = "x")]', ("HttpPost", [], {"Name": ["x"]})),
    ('[HttpGet(@"v\\x")]', ("HttpGet", [["v\\x"]], {})),
    ('[HttpGet(@"a""b")]', ("HttpGet", [['a"b']], {})),
    ('[HttpGet($"/{x}")]', ("HttpGet", [[]], {})),
    ('[HttpGetAttribute("/a")]', ("HttpGet", [["/a"]], {})),
    ("#[Route('/api', name: 'x')]", ("Route", [["/api"]], {"name": ["x"]})),
    ("#[\\Symfony\\Component\\Routing\\Attribute\\Route(path: '/b', methods: ['GET'])]",
     ("Route", [], {"path": ["/b"], "methods": ["GET"]})),
    ('@GetMapping("/a\\"b")', ("GetMapping", [['/a"b']], {})),
    ('@GetMapping("""\n  /tb\n""")', ("GetMapping", [["/tb"]], {})),
    ("@Controller({ path: 'orders', host: h })", ("Controller", [[]], {"path": ["orders"], "host": []})),
    ("@get:JsonProperty(\"x\")", ("JsonProperty", [["x"]], {})),
    ("@Get('a, b')", ("Get", [["a, b"]], {})),
    ("@Get(')(')", ("Get", [[")("]], {})),
])
def test_parse_annotation(text, expect):
    assert stack.parse_annotation(text) == expect


def test_parse_annotations_csharp_list():
    assert stack.parse_annotations('[ApiController, Route("api/[controller]")]') == [
        ("ApiController", [], {}), ("Route", [["api/[controller]"]], {})]
    assert stack.parse_annotations('[HttpGet(@"v"), Produces("a")]') == [("HttpGet", [["v"]], {}), ("Produces", [["a"]], {})]
    assert stack.parse_annotation('[ApiController, Route("x")]') == ("ApiController", [], {})


@pytest.mark.parametrize("text", ["", "@", "[]", "@Get(", "not an annotation", "@Get('x') trailing"])
def test_parse_annotation_unreadable(text):
    assert stack.parse_annotation(text) is None


# annotated_routes through structure.build

def test_spring_exact_routes(make_repo):
    repo = make_repo(SPRING_SRC)
    with_stack(repo, SPRING)
    s = structure.build(repo, "docs/viz-code")
    f = "src/main/java/io/demo/shop/OrderController.java"
    assert routes_of(s, f) == [
        ("GET", "/orders/{id}", f"{CTRL}#get/1", 8), ("GET", "/v1/orders/{id}", f"{CTRL}#get/1", 8),
        ("POST", "/orders", f"{CTRL}#create/0", 10), ("POST", "/v1/orders", f"{CTRL}#create/0", 10),
        ("GET", "/orders/a", f"{CTRL}#two/0", 12), ("GET", "/orders/b", f"{CTRL}#two/0", 12),
        ("GET", "/v1/orders/a", f"{CTRL}#two/0", 12), ("GET", "/v1/orders/b", f"{CTRL}#two/0", 12),
        ("PUT", "/orders/m", f"{CTRL}#viaArg/0", 14), ("PATCH", "/orders/m", f"{CTRL}#viaArg/0", 14),
        ("PUT", "/v1/orders/m", f"{CTRL}#viaArg/0", 14), ("PATCH", "/v1/orders/m", f"{CTRL}#viaArg/0", 14),
        ("ANY", "/orders/any", f"{CTRL}#any/0", 16), ("ANY", "/v1/orders/any", f"{CTRL}#any/0", 16),
        ("GET", "/orders/{PATH}", f"{CTRL}#constant/0", 18), ("GET", "/v1/orders/{PATH}", f"{CTRL}#constant/0", 18),
        ("DELETE", "/orders/{id}", f"{CTRL}#remove/0", 20), ("DELETE", "/v1/orders/{id}", f"{CTRL}#remove/0", 20)]
    assert {(r["framework"], r["source"]) for r in s["facts"][f]["routes"]} == {("spring-mvc", "stack.yaml")}
    # a verb method without a class prefix gives the method path alone
    assert routes_of(s, "src/main/java/io/demo/shop/Health.java") == [
        ("GET", "/health", "io.demo.shop.Health#health/0", 6)]
    # a class prefix with no verb methods gives nothing; no `when` import, no routes
    assert not s["facts"].get("src/main/java/io/demo/shop/Empty.java", {}).get("routes")
    assert not s["facts"].get("src/main/java/io/demo/shop/NoImport.java", {}).get("routes")


def test_annotated_constant_path_is_a_named_segment(make_repo):
    """`@GetMapping(PATH)` keeps its route with the constant as `{PATH}` for the agent to resolve, never dropped."""
    repo = make_repo(SPRING_SRC)
    with_stack(repo, SPRING)
    s = structure.build(repo, "docs/viz-code")
    f = "src/main/java/io/demo/shop/OrderController.java"
    assert [r["path"] for r in s["facts"][f]["routes"] if r["handler"].endswith("#constant/0")] == [
        "/orders/{PATH}", "/v1/orders/{PATH}"]
    p = next(p for p in s["stack"]["patterns"] if p["name"] == "spring-mvc")
    assert (p["matches"], p["files"], p["source"], p["group"], p["form"]) == (19, 2, "stack.yaml", "routes", "annotated")
    md = structure.summary_md(s)
    assert "Route patterns:\n- java spring-mvc (stack.yaml): 19 routes in 2 files\n" in md


def test_a_constant_prefix_keeps_its_routes(make_repo):
    repo = make_repo({**SPRING_SRC, "src/main/java/io/demo/shop/OrderController.java":
                      "package io.demo.shop;\n\nimport org.springframework.web.bind.annotation.*;\n\n"
                      "@RequestMapping(BASE)\npublic class OrderController {\n"
                      "  @GetMapping(\"/{id}\")\n  public String get(String id) { return id; }\n}\n"})
    with_stack(repo, SPRING)
    s = structure.build(repo, "docs/viz-code")
    assert [r["path"] for r in s["facts"]["src/main/java/io/demo/shop/OrderController.java"]["routes"]] == [
        "/{BASE}/{id}"]


def test_jaxrs_path_and_get(make_repo):
    repo = make_repo({
        "pom.xml": "<project><artifactId>shop</artifactId></project>\n",
        "src/main/java/io/demo/shop/Orders.java":
            "package io.demo.shop;\n\nimport jakarta.ws.rs.*;\n\n@Path(\"/orders\")\npublic class Orders {\n"
            "  @GET\n  public String list() { return \"\"; }\n"
            "  @GET\n  @Path(\"{id}\")\n  public String get(@PathParam(\"id\") String id) { return id; }\n"
            "  @Path(\"/sub\")\n  @POST\n  public void post() {}\n"
            "  @Path(\"/no-verb\")\n  public void sub() {}\n}\n",
    })
    with_stack(repo, JAXRS)
    s = structure.build(repo, "docs/viz-code")
    c = "io.demo.shop.Orders"
    assert routes_of(s, "src/main/java/io/demo/shop/Orders.java") == [
        ("GET", "/orders", f"{c}#list/0", 7), ("GET", "/orders/{id}", f"{c}#get/1", 9),
        ("POST", "/orders/sub", f"{c}#post/0", 13)]


def test_nestjs_controller_get(make_repo):
    repo = make_repo({
        "package.json": '{"name": "shop"}\n',
        "src/orders.controller.ts":
            "import { Controller, Get, Post } from '@nestjs/common';\n\n"
            "@Controller('orders')\nexport class OrdersController {\n"
            "  @Get(':id')\n  find(id: string) { return id; }\n"
            "  @Get()\n  all() { return []; }\n"
            "  @Post(`${base}/x`)\n  make() {}\n}\n",
    })
    with_stack(repo, NEST)
    s = structure.build(repo, "docs/viz-code")
    f = "src/orders.controller.ts"
    c = next(n["id"] for n in s["nodes"] if n["kind"] == "class" and n["name"] == "OrdersController").split("::", 1)[1]
    assert routes_of(s, f) == [("GET", "/orders/{id}", f"{c}#find/1", 5), ("GET", "/orders", f"{c}#all/0", 7)]


def test_aspnet_route_and_httpget(make_repo):
    repo = make_repo({
        "Shop/Shop.csproj": "<Project Sdk=\"Microsoft.NET.Sdk.Web\"></Project>\n",
        "Shop/Controllers/OrdersController.cs":
            "using Microsoft.AspNetCore.Mvc;\n\nnamespace Shop.Controllers;\n\n"
            "[ApiController, Route(\"api/[controller]\")]\npublic class OrdersController : ControllerBase {\n"
            "  [HttpGet(\"{id}\")]\n  public string Get(int id) { return \"\"; }\n"
            "  [method: HttpPost(Template = \"[action]\")]\n  public void Create() {}\n"
            "  [HttpDelete, Produces(\"a\")]\n  public void Remove() {}\n}\n",
    })
    with_stack(repo, ASPNET)
    s = structure.build(repo, "docs/viz-code")
    f = "Shop/Controllers/OrdersController.cs"
    c = next(n["id"] for n in s["nodes"] if n["kind"] == "class" and n["name"] == "OrdersController").split("::", 1)[1]
    assert routes_of(s, f) == [("GET", "/api/Orders/{id}", f"{c}#Get/1", 7),
                               ("POST", "/api/Orders/Create", f"{c}#Create/0", 9),
                               ("DELETE", "/api/Orders", f"{c}#Remove/0", 11)]


def test_when_gating_uses_language_separator():
    st = stack.load(None)
    pat = stack.AnnotatedPattern("java", "x", "org.springframework.web", "stack.yaml", ("RequestMapping",),
                                 {"GetMapping": "GET"}, ("value", 0), None, {}, ())
    st.patterns.append(pat)
    nodes = [{"id": "C", "kind": "class", "name": "C", "parent": "p"},
             {"id": "C#m/0", "kind": "method", "name": "m", "parent": "C"}]
    annots = [{"node": "C#m/0", "text": '@GetMapping("/a")', "line": 3}]
    assert stack.find_annotated(st, "java", annots, nodes, ["org.springframework.web.bind.annotation"]) != []
    assert stack.find_annotated(st, "java", annots, nodes, ["org.springframework.webx"]) == []
    assert stack.find_annotated(st, "kotlin", annots, nodes, ["org.springframework.web"]) == []
    # the regex route finder ignores annotated patterns
    assert stack.find_routes(st, "java", '@GetMapping("/a")', ["org.springframework.web"], [], "f") == []


def test_annotated_routes_direct():
    pat = stack.AnnotatedPattern("csharp", "aspnet", None, "pack", ("Route",), {"HttpGet": "GET"}, ("Template", 0),
                                 None, {"[controller]": "class-stem"}, ())
    nodes = [{"id": "K", "kind": "class", "name": "UsersController", "parent": "p"},
             {"id": "K#a/0", "kind": "method", "name": "a", "parent": "K"},
             {"id": "f", "kind": "file", "name": "f.cs", "parent": "p"},
             {"id": "f#top/0", "kind": "method", "name": "top", "parent": "f"}]
    annots = [{"node": "K", "text": '[Route("[controller]/")]', "line": 1},
              {"node": "K", "text": '[Route("v2/[controller]")]', "line": 2},
              {"node": "K#a/0", "text": '[HttpGet("/x/"), HttpGet("y")]', "line": 4},
              {"node": "f#top/0", "text": '[HttpGet("t")]', "line": 9}]
    got = stack.annotated_routes(pat, annots, nodes)
    assert [(r["method"], r["path"], r["handler"], r["line"], r["framework"], r["source"]) for r in got] == [
        ("GET", "/Users/x", "K#a/0", 4, "aspnet", "pack"), ("GET", "/v2/Users/x", "K#a/0", 4, "aspnet", "pack"),
        ("GET", "/Users/y", "K#a/0", 4, "aspnet", "pack"), ("GET", "/v2/Users/y", "K#a/0", 4, "aspnet", "pack"),
        ("GET", "/t", "f#top/0", 9, "aspnet", "pack")]


# validation

def test_load_annotated(tmp_path):
    st = stack.load(write(tmp_path, SPRING + JAXRS.removeprefix("java:\n  routes:\n") + ASPNET))
    sp = next(p for p in st.patterns if p.name == "spring-mvc")
    assert isinstance(sp, stack.AnnotatedPattern)
    assert (sp.lang, sp.when, sp.source, sp.prefix, sp.path_args, sp.method_arg, sp.token, sp.method_path) == (
        "java", "org.springframework.web.bind.annotation", "stack.yaml", ("RequestMapping",), ("value", "path", 0),
        "method", {}, ())
    assert sp.verbs["RequestMapping"] == "from-method-arg" and sp.verbs["GetMapping"] == "GET"
    jx = next(p for p in st.patterns if p.name == "jax-rs")
    assert jx.path_args == ("value", "path", 0) and jx.method_path == ("Path",)
    asp = next(p for p in st.patterns if p.name == "aspnet")
    assert asp.token == {"[controller]": "class-stem", "[action]": "method-name"} and asp.path_args == ("Template", 0)
    assert stack.covered(st, "java", "org.springframework.web.bind.annotation.GetMapping")


A = "java:\n  routes:\n    - {name: a, form: annotated, "


@pytest.mark.parametrize("text,expect", [
    (A + "}\n", "java.routes[0] (a): missing verbs"),
    (A + "verbs: {}}\n", "java.routes[0] (a): verbs must be a non-empty mapping"),
    (A + "verbs: [GetMapping]}\n", "verbs must be a non-empty mapping"),
    (A + "verbs: {GetMapping: 'GET X'}}\n", "verb GetMapping: 'GET X' is not an HTTP method word or from-method-arg"),
    (A + "verbs: {GetMapping: GET}, regex: 'x'}\n", "java.routes[0] (a): unknown key 'regex'"),
    (A + "verbs: {GetMapping: GET}, path: literal}\n", "unknown key 'path'"),
    (A + "verbs: {GetMapping: GET}, method: GET}\n", "unknown key 'method'"),
    (A + "verbs: {GetMapping: GET}, prefix: RequestMapping}\n", "prefix must be a list of annotation names"),
    (A + "verbs: {GetMapping: GET}, method_path: [3]}\n", "method_path must be a list of annotation names"),
    (A + "verbs: {GetMapping: GET}, path_args: []}\n", "path_args must be a non-empty list of argument names or positions"),
    (A + "verbs: {GetMapping: GET}, path_args: [true]}\n", "path_args must be a non-empty list"),
    (A + "verbs: {GetMapping: GET}, path_args: 0}\n", "path_args must be a non-empty list"),
    (A + "verbs: {GetMapping: GET}, path_args: [-1]}\n", "path_args must be a non-empty list"),
    (A + "verbs: {GetMapping: GET}, method_arg: 3}\n", "method_arg must be an argument name"),
    (A + "verbs: {GetMapping: GET}, token: {'[c]': stem}}\n",
     "token '[c]': unknown replacement 'stem' (one of class-stem, method-name)"),
    (A + "verbs: {GetMapping: GET}, when: 3}\n", "when must be an import prefix"),
    ("java:\n  routes:\n    - {name: a, form: tree, verbs: {GetMapping: GET}}\n",
     "java.routes[0] (a): unknown form 'tree' (regex or annotated)"),
    ("java:\n  routes:\n    - {form: annotated, verbs: {GetMapping: GET}}\n", "java.routes[0]: missing name"),
    (A + "verbs: {G: GET}}\n    - {name: a, path: literal, method: GET, regex: '(?P<path>x)'}\n",
     "java.routes[1] (a): duplicate route name"),
    ("java:\n  routes:\n    - {name: a, path: literal, method: GET, regex: '(?P<path>x)'}\n"
     "    - {name: a, form: annotated, verbs: {G: GET}}\n", "java.routes[1] (a): duplicate route name"),
    ("python:\n  routes:\n    - {name: fastapi, form: annotated, verbs: {get: GET}}\n",
     "python.routes[0] (fastapi): clashes with a built-in rule"),
    ("scala:\n  routes:\n    - {name: s, form: annotated, verbs: {get: GET}}\n",
     "scala.routes[0] (s): the annotated form needs a language the generic walker parses (not scala)"),
])
def test_bad_annotated_entries(tmp_path, text, expect):
    with pytest.raises(stack.StackError) as e:
        stack.load(write(tmp_path, text))
    assert "stack.yaml: " in str(e.value) and expect in str(e.value)


def test_regex_form_explicit(tmp_path):
    st = stack.load(write(tmp_path, "java:\n  routes:\n    - {name: r, form: regex, path: literal, method: GET, "
                                    "regex: '(?P<path>/a)'}\n"))
    assert isinstance(next(p for p in st.patterns if p.name == "r"), stack.RoutePattern)


def test_zero_match_annotated_flagged(make_repo):
    repo = make_repo(SPRING_SRC)
    with_stack(repo, SPRING.replace("GetMapping: GET, PostMapping: POST, PutMapping: PUT, DeleteMapping: DELETE, "
                                    "PatchMapping: PATCH,\n              RequestMapping: from-method-arg", "Nope: GET")
               .replace("prefix: [RequestMapping]", "prefix: [Nope]"))
    s = structure.build(repo, "docs/viz-code")
    dead = next(p for p in s["stack"]["patterns"] if p["name"] == "spring-mvc")
    assert dead["matches"] == 0 and dead["first_file"] == "src/main/java/io/demo/shop/Empty.java:3"
    assert stack.count(s["stack"]) >= 1
    md = structure.summary_md(s)
    assert ("- java spring-mvc (stack.yaml): 0 matches — check the annotation names against "
            "src/main/java/io/demo/shop/Empty.java:3\n") in md
