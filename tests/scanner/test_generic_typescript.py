from vizcode import ids, structure
from vizcode.adapters import generic
from vizcode.adapters.langs import BY_SUFFIX, SPECS

TS = SPECS["typescript"]
MOD = {"id": "mod:web", "path": "web", "lang": "typescript", "build": "dir"}
FILE = "web/src/orders/orders.controller.ts"
GOLDEN = """import { a, b as c } from "x";
import * as y from "./rel";
import Def from "@scope/pkg";
import "side-effect";
const fs = require("fs");

@Controller("orders")
export class OrdersController extends Base<T> implements IOrders, ns.Other {
  constructor(private readonly repo: Repo) { super(); }

  @Get(":id")
  async find(id: string, ...rest: number[]): Promise<Order> {
    const f = (x) => x.id;
    return this.repo.find(`orders/${id}/${rest.length}`).then(f);
  }

  private url(a = 1, { b }: Opts = {}): string {
    return process.env.DB_URL ?? process.env["X"];
  }
}

export const handler = async (event: Event): Promise<void> => {
  await new Client<string>(1).send(event);
};
export function plain(a: number): number { return a; }
const g = function (q) { return q; }, n = 5;
let h = 1;
"""
PKG = "web::src/orders/"
# a folder package may hold two files defining one class name: classes carry the file stem
CTRL = "web::src/orders.orders.controller.OrdersController"
FILE_ID = f"{PKG}orders.controller.ts"


def parse(src: str, rel: str = FILE, spec=TS):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=spec)


def test_typescript_spec_registered():
    assert BY_SUFFIX[".ts"] is TS and TS.grammar == "typescript" and TS.package == "dir"
    tsx = BY_SUFFIX[".tsx"]
    assert tsx.lang == "typescript" and tsx.grammar == "tsx"
    assert structure.LANGS[".ts"][0] == "typescript" and structure.LANGS[".tsx"][0] == "typescript"


def test_typescript_nodes():
    res = parse(GOLDEN)
    assert res["package"] == "src/orders"
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        # decorators before a declaration open its span, as Java's annotations do
        (CTRL, "class", "OrdersController", PKG, 7, "public"),
        (f"{CTRL}#constructor/1", "method", "constructor", CTRL, 9, "public"),
        (f"{CTRL}#find/2", "method", "find", CTRL, 11, "public"),
        (f"{CTRL}#url/2", "method", "url", CTRL, 17, "private"),
        (FILE_ID, "file", "orders.controller.ts", PKG, 1, "public"),
        # a name bound to a function value is a function; `n = 5`, `h = 1` and the arrow in find are not
        (f"{FILE_ID}#handler/1", "method", "handler", FILE_ID, 22, "public"),
        (f"{FILE_ID}#plain/1", "method", "plain", FILE_ID, 25, "public"),
        (f"{FILE_ID}#g/1", "method", "g", FILE_ID, 26, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    assert n[CTRL]["metrics"] == {"loc": 14, "methods": 3}
    assert n[f"{CTRL}#find/2"]["metrics"]["loc"] == 5
    assert n[f"{CTRL}#constructor/1"]["signature"] == {"params": [{"name": "repo", "type": "Repo"}],
                                                       "returns": None}
    assert n[f"{CTRL}#find/2"]["signature"] == {"params": [{"name": "id", "type": "string"},
                                                           {"name": "*rest", "type": "number[]"}],
                                                "returns": "Promise<Order>"}
    # a default value is not a type; a destructured parameter is named by its first key
    assert n[f"{CTRL}#url/2"]["signature"] == {"params": [{"name": "a", "type": None}, {"name": "b", "type": "Opts"}],
                                               "returns": "string"}
    assert n[f"{FILE_ID}#handler/1"]["signature"] == {"params": [{"name": "event", "type": "Event"}],
                                                      "returns": "Promise<void>"}
    assert n[f"{FILE_ID}#g/1"]["signature"] == {"params": [{"name": "q", "type": None}], "returns": None}
    assert res["supers"] == [(CTRL, ["Base", "IOrders", "ns.Other"])]


def test_typescript_facts():
    res = parse(GOLDEN)
    assert res["imports"] == [
        {"target": "x", "line": 1, "relative": False, "names": ["a", "b"], "renames": {"c": "b"}},
        {"target": "./rel", "line": 2, "relative": True, "names": [], "as": "y"},
        {"target": "@scope/pkg", "line": 3, "relative": False, "names": []},
        {"target": "side-effect", "line": 4, "relative": False, "names": []},
        {"target": "fs", "line": 5, "relative": False, "names": []},
    ]
    find, handler = f"{CTRL}#find/2", f"{FILE_ID}#handler/1"
    # decorators are not calls
    assert res["calls"] == [
        {"callee": "super", "in": f"{CTRL}#constructor/1", "line": 9, "args": 0},
        {"callee": "this.repo.find(`orders/${id}/${rest.length}`).then", "in": find, "line": 14, "args": 1},
        {"callee": "this.repo.find", "in": find, "line": 14, "args": 1},
        {"callee": "new Client(1).send", "in": handler, "line": 23, "args": 1},
        {"callee": "Client", "in": handler, "line": 23, "args": 1},
    ]
    assert res["strings"] == [
        {"text": "orders", "line": 7, "in": None},
        {"text": ":id", "line": 11, "in": None},
        {"text": "orders/{id}/{rest.length}", "line": 14, "in": find},
        {"text": "X", "line": 18, "in": f"{CTRL}#url/2"},
    ]
    assert res["env_keys"] == [{"key": "DB_URL", "line": 18}, {"key": "X", "line": 18}]
    assert res["annotations"] == [
        {"node": CTRL, "text": '@Controller("orders")', "line": 7},
        {"node": find, "text": '@Get(":id")', "line": 11},
    ]


def test_typescript_other_forms():
    src = ('const f = x => x;\nf(...xs);\nimport z = require("z");\nconst m = await import("./lazy");\n'
           'export { q } from "./q";\ninterface Repo extends Base { find(id: string): Order; }\n')
    res = parse(src, "web/r.ts")
    assert res["package"] == "_root_"
    assert [(n["id"], n["signature"]["params"] if "signature" in n else None) for n in res["nodes"]] == [
        ("web::_root_/r.ts", None), ("web::_root_/r.ts#f/1", [{"name": "x", "type": None}]),
        ("web::r.Repo", None), ("web::r.Repo#find/1", [{"name": "id", "type": "string"}]),
    ]
    assert {"callee": "f", "in": None, "line": 2, "args": None} in res["calls"]
    assert [(i["target"], i["relative"], i["names"]) for i in res["imports"]] == [
        ("z", False, []), ("./lazy", True, []), ("./q", True, ["q"])]
    assert res["supers"] == [("web::r.Repo", ["Base"])]


def test_tsx_parses_jsx():
    src = 'export const App = (p: Props) => <div title="x">{p.a}</div>;\n'
    tsx = BY_SUFFIX[".tsx"]
    res = parse(src, "web/src/App.tsx", tsx)
    assert res["parse_error"] is False
    assert [n["id"] for n in res["nodes"]] == ["web::src/App.tsx", "web::src/App.tsx#App/1"]
    assert res["strings"] == [{"text": "x", "line": 1, "in": "web::src/App.tsx#App/1"}]
    assert parse(src, "web/src/App.ts")["parse_error"] is True


def test_typescript_non_ascii():
    res = parse("export function grüße(n: string) { return `Grüße ${n}`; }\n", "web/é/g.ts")
    assert res["package"] == "é"
    assert [n["id"] for n in res["nodes"]] == ["web::é/g.ts", "web::é/g.ts#grüße/1"]
    assert res["strings"] == [{"text": "Grüße {n}", "line": 1, "in": "web::é/g.ts#grüße/1"}]


def test_typescript_survives_broken_file():
    src = "class Ok { fine() { go(); } }\n\nclass Broken {\n  half(x: number) {\n    call(\n"
    res = parse(src, "web/b.ts")
    assert res["parse_error"] is True
    assert [n["id"] for n in res["nodes"]][:2] == ["web::b.Ok", "web::b.Ok#fine/0"]
    assert {"callee": "go", "in": "web::b.Ok#fine/0", "line": 1, "args": 0} in res["calls"]


def test_typescript_end_to_end(make_repo):
    repo = make_repo({"web/src/orders/orders.controller.ts": GOLDEN, "web/src/orders/orders.service.ts":
                      "export class OrdersService {}\nexport class OrdersController {}\n"})
    s = structure.build(repo)
    f = "web/src/orders/orders.controller.ts"
    assert s["files"][f]["lang"] == "typescript"
    ids_ = {n["id"] for n in s["nodes"]}
    # one class name in two files of a folder: two nodes
    assert {"web::src/orders.orders.controller.OrdersController",
            "web::src/orders.orders.service.OrdersController"} <= ids_
    assert [e["key"] for e in s["facts"][f]["env_keys"]] == ["DB_URL", "X"]


def test_typescript_destructured_default_parameter_names():
    res = parse("function f({a}: T = foo, {b: c}: U, d: number = bar) {}\n", "web/d.ts")
    sig = res["nodes"][-1]["signature"]
    assert sig["params"] == [{"name": "a", "type": "T"}, {"name": "b", "type": "U"}, {"name": "d", "type": "number"}]


def test_a_function_valued_property_of_an_object_is_a_method():
    """`export const authService = { me: async () => .., logout: function () {..} }`: each is a method of the
    file, and the calls inside are its own."""
    res = parse("export const authService = {\n  me: async () => http.get('me'),\n"
                "  logout: function () { return http.post('logout') },\n  base: '/api',\n}\n", "web/authService.ts")
    me, out = "web::_root_/authService.ts#me/0", "web::_root_/authService.ts#logout/0"
    assert [n["id"] for n in res["nodes"] if n["kind"] == "method"] == [me, out]
    assert [(c["callee"], c["in"]) for c in res["calls"]] == [("http.get", me), ("http.post", out)]
    # an object passed to a call is no service: its function properties stay inside the call
    res = parse("app.route({ url: '/x', handler: async () => 1 })\n", "web/r.ts")
    assert [n for n in res["nodes"] if n["kind"] == "method"] == []
