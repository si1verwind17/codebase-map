import pytest

from vizcode.scan import proto, structure

OCCUPANCY_PROTO = '''syntax = "proto3";

package parking.occupancy.v1;

// Bay state changes flow from sensor-gateway to occupancy over one
// long-lived bidirectional stream; occupancy acknowledges each batch so the
// gateway can drop it from its retry buffer.
service OccupancyFeed {
  rpc Stream(stream BayUpdate) returns (stream Ack);
}

message BayUpdate {
  string zone_id = 1;
}

message Ack {
  string sequence = 1;
  bool accepted = 2;
}
'''

UPLINK = '''import asyncio
import logging

import grpc

import occupancy_pb2
import occupancy_pb2_grpc
from common_py.config import env

log = logging.getLogger("sensor-gateway.uplink")


class OccupancyUplink:
    """Client side of the OccupancyFeed/Stream bidirectional gRPC stream."""

    async def run(self, outbox: asyncio.Queue) -> None:
        async with grpc.aio.insecure_channel(env("OCCUPANCY_GRPC_ADDR")) as channel:
            stub = occupancy_pb2_grpc.OccupancyFeedStub(channel)

            async def updates():
                while True:
                    u = await outbox.get()
                    yield occupancy_pb2.BayUpdate(**u)

            async for ack in stub.Stream(updates()):
                if not ack.accepted:
                    log.warning("occupancy rejected sequence %s", ack.sequence)
'''

SERVER = '''import logging

import occupancy_pb2
import occupancy_pb2_grpc


class OccupancyFeedService(occupancy_pb2_grpc.OccupancyFeedServicer):
    def Stream(self, request_iterator, context):
        for update in request_iterator:
            yield occupancy_pb2.Ack(sequence=update.sequence, accepted=True)
'''

MAIN = '''from concurrent import futures

import grpc

import occupancy_pb2_grpc

from .grpc_server import OccupancyFeedService


def serve() -> None:
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
    occupancy_pb2_grpc.add_OccupancyFeedServicer_to_server(OccupancyFeedService(), server)
    server.start()
'''

KEY = "grpc parking.occupancy.v1.OccupancyFeed/Stream"


def test_proto_services_rpcs_and_streaming_sides():
    p = proto.parse(OCCUPANCY_PROTO, "proto/occupancy.proto")
    assert p == {"file": "proto/occupancy.proto", "package": "parking.occupancy.v1", "services": [
        {"name": "OccupancyFeed", "line": 8, "rpcs": [
            {"name": "Stream", "request": "BayUpdate", "response": "Ack", "client_streams": True,
             "server_streams": True, "line": 9, "key": KEY}]}],
        "messages": [{"name": "BayUpdate", "line": 12, "loc": 3, "fields": [{"name": "zone_id", "type": "string"}]},
                     {"name": "Ack", "line": 16, "loc": 4, "fields": [{"name": "sequence", "type": "string"},
                                                                     {"name": "accepted", "type": "bool"}]}]}


def test_proto_unary_rpc_options_comments_and_no_package():
    src = ('syntax = "proto3";\n/* service Hidden { rpc X(A) returns (B); } */\n'
           'service Quotes {\n  // rpc Old(A) returns (B);\n'
           '  rpc Get (GetReq) returns (GetResp) {\n    option (google.api.http) = { get: "/v1/q" };\n  }\n'
           '  rpc Watch(.pkg.WatchReq) returns (stream Tick);\n}\n')
    p = proto.parse(src, "q.proto")
    assert p["package"] is None
    assert [(r["name"], r["request"], r["response"], r["client_streams"], r["server_streams"], r["line"], r["key"])
            for s in p["services"] for r in s["rpcs"]] == [
        ("Get", "GetReq", "GetResp", False, False, 5, "grpc Quotes/Get"),
        ("Watch", ".pkg.WatchReq", "Tick", False, True, 8, "grpc Quotes/Watch")]


def test_stub_ends():
    assert proto.call_end("occupancy_pb2_grpc.OccupancyFeedStub") == ("client", "OccupancyFeed")
    assert proto.call_end("occupancy_pb2_grpc.add_OccupancyFeedServicer_to_server") == ("server", "OccupancyFeed")
    assert proto.call_end("OccupancyFeedGrpc.stub") == ("client", "OccupancyFeed")
    assert proto.call_end("OccupancyFeedGrpc.bindService") == ("server", "OccupancyFeed")
    assert proto.call_end("stub.Stream") is None
    assert proto.base_end("occupancy_pb2_grpc.OccupancyFeedServicer") == "OccupancyFeed"
    assert proto.base_end("OccupancyFeedGrpc.OccupancyFeed") == "OccupancyFeed"
    assert proto.base_end("Servicer") is None


def test_grpc_ends_are_tied_to_proto_keys(make_repo):
    repo = make_repo({"proto/occupancy.proto": OCCUPANCY_PROTO,
                      "sensor_gateway/app/__init__.py": "", "sensor_gateway/app/uplink.py": UPLINK,
                      "occupancy/app/__init__.py": "", "occupancy/app/grpc_server.py": SERVER,
                      "occupancy/app/main.py": MAIN})
    s = structure.build(repo)
    assert [svc["name"] for p in s["proto"] for svc in p["services"]] == ["OccupancyFeed"]
    client = s["facts"]["sensor_gateway/app/uplink.py"]["grpc"]
    # the request is where the rpc is called on the stub, not where the stub is made (line 18)
    assert client == [{"side": "client", "service": "OccupancyFeed", "keys": [KEY],
                       "in": "sensor_gateway/app::app.uplink.OccupancyUplink#run/1", "line": 25}]
    server = s["facts"]["occupancy/app/grpc_server.py"]["grpc"]
    assert server == [{"side": "server", "service": "OccupancyFeed", "keys": [KEY],
                       "in": "occupancy/app::app.grpc_server.OccupancyFeedService", "line": 7}]
    reg = s["facts"]["occupancy/app/main.py"]["grpc"]
    assert reg == [{"side": "server", "service": "OccupancyFeed", "keys": [KEY],
                    "in": "occupancy/app::app.main#serve/0", "line": 12}]
    md = structure.summary_md(s)
    assert (f"- {KEY}: rpc Stream(stream BayUpdate) returns (stream Ack), bidirectional streaming "
            "(proto/occupancy.proto:9)") in md
    svc = KEY   # written out in full, never the `Svc/{A,B}` brace form
    assert "/{" not in md
    assert (f"- **grpc clients:** {svc} ← sensor_gateway/app::app.uplink.OccupancyUplink#run/1 "
            "(sensor_gateway/app/uplink.py:25)") in md
    # each service once, with all its ends
    assert (f"- **grpc servers:** {svc} ← occupancy/app::app.grpc_server.OccupancyFeedService "
            "(occupancy/app/grpc_server.py:7), occupancy/app::app.main#serve/0 (occupancy/app/main.py:12)\n") in md


def test_a_stub_with_no_proto_still_listed_without_keys(make_repo):
    repo = make_repo({"gw/__init__.py": "", "gw/c.py": "import x_pb2_grpc\n\n\ndef go(ch):\n"
                                                         "    return x_pb2_grpc.PaymentsStub(ch)\n"})
    s = structure.build(repo)
    assert s["proto"] == []
    assert s["facts"]["gw/c.py"]["grpc"] == [{"side": "client", "service": "Payments", "keys": [],
                                              "in": "gw::gw.c#go/1", "line": 5}]
    assert "- **grpc clients:** Payments (no .proto in repo) ← gw::gw.c#go/1 (gw/c.py:5)" in structure.summary_md(s)


def test_unrelated_stub_names_are_not_grpc_ends(make_repo):
    repo = make_repo({"proto/occupancy.proto": OCCUPANCY_PROTO,
                      "gw/__init__.py": "",
                      "gw/c.py": ("from x import FakePaymentsStub, OccupancyFeedStub\n\n\n"
                                  "def go(ch):\n    a = createStub(ch)\n    b = FakePaymentsStub(ch)\n"
                                  "    return OccupancyFeedStub(ch)\n\n\nclass Fake(Servicer):\n    pass\n")})
    s = structure.build(repo)
    # a name known from a .proto is an end even without a _pb2_grpc receiver; other names are not
    assert s["facts"]["gw/c.py"]["grpc"] == [{"side": "client", "service": "OccupancyFeed", "keys": [KEY],
                                              "in": "gw::gw.c#go/1", "line": 7}]


def test_vendored_protos_are_skipped(make_repo):
    vendored = 'syntax = "proto3";\npackage google.longrunning;\nservice Operations {\n  rpc GetOperation(A) returns (B);\n}\n'
    repo = make_repo({"proto/occupancy.proto": OCCUPANCY_PROTO,
                      "third_party/googleapis/google/longrunning/operations.proto": vendored,
                      "vendor/x/ops.proto": vendored,
                      "api/google/protobuf/ops.proto": vendored,
                      "app/__init__.py": "", "app/m.py": "def f():\n    pass\n"})
    assert [p["file"] for p in structure.build(repo)["proto"]] == ["proto/occupancy.proto"]


# --- gRPC ends in each language, named as protoc's gRPC plugin names generated code -------------------------

SHOP_PROTO = '''syntax = "proto3";
package shop.v1;

service Orders {
  rpc Place(PlaceRequest) returns (PlaceReply);
}

message PlaceRequest {
  string sku = 1;
  repeated Line lines = 2;
  message Line { string sku = 1; int32 qty = 2; }
}

message PlaceReply { string id = 1; }
'''
SHOP_KEY = "grpc shop.v1.Orders/Place"

GO_SERVER = '''package main

import (
	pb "example.com/shop/genproto"
	"google.golang.org/grpc"
)

type server struct {
	pb.UnimplementedOrdersServer
}

func main() {
	s := grpc.NewServer()
	pb.RegisterOrdersServer(s, &server{})
}
'''
GO_CLIENT = '''package web

func Place(conn *grpc.ClientConn) {
	c := pb.NewOrdersClient(conn)
	c.Place(ctx, &pb.PlaceRequest{})
}
'''
CS_SERVER = '''namespace Shop.Orders;

public class OrdersService : Orders.OrdersBase
{
    public override Task<PlaceReply> Place(PlaceRequest r, ServerCallContext ctx) => Task.FromResult(new PlaceReply());
}
'''
CS_PROGRAM = '''namespace Shop.Orders;

public static class Setup
{
    public static void Map(WebApplication app) { app.MapGrpcService<OrdersService>(); }
}
'''
CS_CLIENT = '''namespace Shop.Web;

public class Client
{
    public void Go(GrpcChannel ch) { var c = new Orders.OrdersClient(ch); c.Place(new PlaceRequest()); }
    public void Wire(IServiceCollection s) { s.AddGrpcClient<Orders.OrdersClient>(o => {}); }
}
'''
JS_SERVER = '''const grpc = require('@grpc/grpc-js');
const loader = require('@grpc/proto-loader');

function place(call, cb) { cb(null, {}); }

function main() {
  const shop = grpc.loadPackageDefinition(loader.loadSync('shop.proto')).shop.v1;
  const server = new grpc.Server();
  server.addService(shop.Orders.service, { place });
}
'''
TS_CLIENT = '''import * as grpc from '@grpc/grpc-js';

export function place(shop: any) {
  const c = new shop.Orders('orders:50051', grpc.credentials.createInsecure());
  c.place({}, () => {});
}
'''
TS_NOT_GRPC = '''export function make(models: any) {
  return new models.Orders();
}
'''
KT_SERVER = '''package shop.orders

class OrdersImpl : OrdersGrpcKt.OrdersCoroutineImplBase() {
    override suspend fun place(r: PlaceRequest): PlaceReply = PlaceReply.getDefaultInstance()
}
'''
KT_CLIENT = '''package shop.web

class Client(val ch: ManagedChannel) {
    fun go() = OrdersGrpcKt.OrdersCoroutineStub(ch)
}
'''
JAVA_SERVER = '''package shop.orders;

public class OrdersImpl extends OrdersGrpc.OrdersImplBase {
  public void place(PlaceRequest r, StreamObserver<PlaceReply> o) {}
}
'''
JAVA_CLIENT = '''package shop.web;

public class Client {
  Object go(Channel ch) { return OrdersGrpc.newBlockingStub(ch); }
}
'''

LANG_CASES = {
    "go": ({"orders/main.go": GO_SERVER, "web/client.go": GO_CLIENT},
           {"orders/main.go": [("server", "orders::server"), ("server", "orders::_root_/main.go#main/0")],
            "web/client.go": [("client", "web::_root_/client.go#Place/1")]}),
    "csharp": ({"Orders/OrdersService.cs": CS_SERVER, "Orders/Program.cs": CS_PROGRAM, "Web/Client.cs": CS_CLIENT},
               {"Orders/OrdersService.cs": [("server", "Orders::Shop.Orders.OrdersService")],
                "Orders/Program.cs": [("server", "Orders::Shop.Orders.Setup#Map/1")],
                # the `Place` call is the request; the `AddGrpcClient` registration sends nothing
                "Web/Client.cs": [("client", "Web::Shop.Web.Client#Go/1")]}),
    "node": ({"orders/server.js": JS_SERVER, "web/client.ts": TS_CLIENT, "web/models.ts": TS_NOT_GRPC},
             {"orders/server.js": [("server", "orders::_root_/server.js#main/0")],
              "web/client.ts": [("client", "web::_root_/client.ts#place/1")], "web/models.ts": []}),
    "kotlin": ({"orders/Server.kt": KT_SERVER, "web/Client.kt": KT_CLIENT},
               {"orders/Server.kt": [("server", "orders::shop.orders.OrdersImpl")],
                "web/Client.kt": [("client", "web::shop.web.Client#go/0")]}),
    "java": ({"orders/OrdersImpl.java": JAVA_SERVER, "web/Client.java": JAVA_CLIENT},
             {"orders/OrdersImpl.java": [("server", "orders::shop.orders.OrdersImpl")],
              "web/Client.java": [("client", "web::shop.web.Client#go/1")]}),
}


@pytest.mark.parametrize("lang", LANG_CASES)
def test_grpc_ends_in_each_language(make_repo, lang):
    files, want = LANG_CASES[lang]
    s = structure.build(make_repo({"proto/shop.proto": SHOP_PROTO, **files}))
    got = {f: [(g["side"], g["in"]) for g in s["facts"][f]["grpc"]] for f in want}
    assert got == want
    assert all(g["service"] == "Orders" and g["keys"] == [SHOP_KEY] for f in want for g in s["facts"][f]["grpc"])


def test_go_registration_names_need_a_proto_service(make_repo):
    repo = make_repo({"web/client.go": "package web\n\nfunc Go() {\n\tc := api.NewHTTPClient(x)\n"
                                       "\tapi.RegisterHandlerServer(s)\n}\n"})
    assert structure.build(repo)["facts"]["web/client.go"]["grpc"] == []


def test_proto_messages_parsed_with_nested_and_oneof_fields():
    src = ('syntax = "proto3";\nmessage A {\n  map<string, int32> counts = 1;\n  oneof pay { string card = 2; '
           'int64 points = 3; }\n  enum Kind { X = 0; Y = 1; }\n  Kind kind = 4 [deprecated = true];\n'
           '  message B { optional string id = 1; }\n  repeated B bs = 5;\n}\nenum Top { Z = 0; }\n')
    assert proto.parse(src, "a.proto")["messages"] == [
        {"name": "A", "line": 2, "loc": 8, "fields": [
            {"name": "counts", "type": "map<string,int32>"}, {"name": "card", "type": "string"},
            {"name": "points", "type": "int64"}, {"name": "kind", "type": "Kind"}, {"name": "bs", "type": "repeated B"}]},
        {"name": "A.B", "line": 7, "loc": 1, "fields": [{"name": "id", "type": "string"}]}]


def test_proto_messages_become_types_of_the_module_holding_the_proto(make_repo):
    gen = ('// Code generated by protoc-gen-go. DO NOT EDIT.\npackage genproto\n\n'
           'type PlaceRequest struct {\n\tstate protoimpl.MessageState\n\tsizeCache protoimpl.SizeCache\n'
           '\tunknownFields protoimpl.UnknownFields\n\n\tSku string\n}\n\nfunc (x *PlaceRequest) GetSku() string { return x.Sku }\n')
    repo = make_repo({"proto/shop.proto": SHOP_PROTO,            # in no module: keys only
                      "orders/proto/shop.proto": SHOP_PROTO, "orders/server.js": JS_SERVER,
                      "checkout/proto/shop.proto": SHOP_PROTO, "checkout/genproto/shop.pb.go": gen,
                      "checkout/main.go": "package main\n\nfunc main() {}\n"})
    s = structure.build(repo)
    types = {n["id"]: (n["name"], n["parent"], n["lang"], n.get("fields")) for n in s["nodes"]
             if n["kind"] == "class"}
    assert types == {
        "orders::shop.v1.PlaceRequest": ("PlaceRequest", "orders::shop.v1/", "proto", [
            {"name": "sku", "type": "string"}, {"name": "lines", "type": "repeated Line"}]),
        "orders::shop.v1.PlaceRequest.Line": ("Line", "orders::shop.v1.PlaceRequest", "proto", [
            {"name": "sku", "type": "string"}, {"name": "qty", "type": "int32"}]),
        "orders::shop.v1.PlaceReply": ("PlaceReply", "orders::shop.v1/", "proto", [{"name": "id", "type": "string"}]),
        # the module's generated code declares PlaceRequest: no second copy from the .proto, nor of its nested Line;
        # it keeps its exported fields only, not the generator's bookkeeping (`state`, `sizeCache`, ...)
        "checkout::genproto.PlaceRequest": ("PlaceRequest", "checkout::genproto/", "go", [
            {"name": "Sku", "type": "string"}]),
        "checkout::shop.v1.PlaceReply": ("PlaceReply", "checkout::shop.v1/", "proto", [{"name": "id", "type": "string"}]),
    }
    assert {n["id"]: n["kind"] for n in s["nodes"] if n["id"] == "orders::shop.v1/"} == {"orders::shop.v1/": "package"}


def test_summary_lists_a_copied_proto_once_per_key(make_repo):
    repo = make_repo({"proto/shop.proto": SHOP_PROTO, "orders/proto/shop.proto": SHOP_PROTO,
                      "web/proto/shop.proto": SHOP_PROTO, "web/client.go": GO_CLIENT})
    md = structure.summary_md(structure.build(repo))
    assert md.count(f"- {SHOP_KEY}:") == 1
    assert (f"- {SHOP_KEY}: rpc Place(PlaceRequest) returns (PlaceReply), unary (orders/proto/shop.proto:5, "
            "proto/shop.proto:5, web/proto/shop.proto:5)") in md
    assert f"- **grpc clients:** {SHOP_KEY} ← web::_root_/client.go#Place/1 (web/client.go:5)" in md   # the `c.Place` call


CART_PROTO = '''syntax = "proto3";
package cart.v1;

service Cart {
  rpc GetCart(GetCartRequest) returns (CartReply);
  rpc AddItem(AddItemRequest) returns (CartReply);
}

message GetCartRequest { string id = 1; }
message AddItemRequest { string id = 1; }
message CartReply { string id = 1; }
'''


def test_grpc_requests_are_rpc_calls_on_a_stub_not_its_server_or_own_object(make_repo):
    """Only the rpc called is a request (`AddItem` never is here); a stub held by another module's value named as
    one counts; a server forwarding to its store, a call on the caller's own object and a wrapper object do not."""
    repo = make_repo({
        "proto/cart.proto": CART_PROTO,
        "go.mod": "module shop\n",
        "web/cart.go": "package web\n\nfunc View(conn *grpc.ClientConn) {\n\tc := pb.NewCartClient(conn)\n"
                       "\tc.GetCart(ctx, &pb.GetCartRequest{})\n}\n",
        "web/helper.go": "package web\n\ntype Page struct{}\n\nfunc (p *Page) Show() {\n\tp.AddItem()\n}\n\n"
                         "func (p *Page) AddItem() {}\n",
        "carts/server.go": "package carts\n\ntype server struct {\n\tpb.UnimplementedCartServer\n\tstore Store\n}\n\n"
                           "func (s *server) GetCart(ctx context.Context, r *pb.GetCartRequest) (*pb.CartReply, error) {\n"
                           "\treturn s.store.GetCart(ctx, r.Id)\n}\n",
    })
    s = structure.build(repo)
    clients = [(f, g["keys"], g["line"]) for f, ff in s["facts"].items() for g in ff.get("grpc", [])
               if g["side"] == "client"]
    assert clients == [("web/cart.go", ["grpc cart.v1.Cart/GetCart"], 5)]


STORE_PROTO = '''syntax = "proto3";
package store.v1;

service Store {
  rpc Get(Key) returns (Value);
  rpc Check(Key) returns (Value);
}

message Key { string k = 1; }
message Value { string v = 1; }
'''


def test_only_a_call_on_the_stub_is_a_grpc_request(make_repo):
    """`conf.get`, `requests.get`, `redis_client.get` and `api_client.check` share the rpcs' names but not the stub."""
    repo = make_repo({
        "proto/store.proto": STORE_PROTO,
        "gw/app/__init__.py": "",
        "gw/app/up.py": "import grpc\nimport requests\nimport store_pb2_grpc\n\n\nclass Up:\n    def run(self, conf):\n"
                        "        self.stub = store_pb2_grpc.StoreStub(grpc.insecure_channel('x'))\n"
                        "        conf.get('host')\n        requests.get('http://x')\n        return self.stub.Get(1)\n",
        "other/app/__init__.py": "",
        "other/app/cache.py": "def read(redis_client, api_client):\n    redis_client.get('k')\n    api_client.check('k')\n",
    })
    s = structure.build(repo)
    clients = [(f, g["keys"], g["line"]) for f, ff in s["facts"].items() for g in ff.get("grpc", []) if g["side"] == "client"]
    assert clients == [("gw/app/up.py", ["grpc store.v1.Store/Get"], 11)]


def test_stub_shapes_and_a_module_whose_calls_the_scan_cannot_see(make_repo):
    """Java `newBlockingStub`, a Python stub behind a property, and a module whose chained call is unseen: it keeps
    its stub end while another module's call is its own request."""
    repo = make_repo({
        "proto/cart.proto": CART_PROTO,
        "pom.xml": "<project/>\n",
        "src/main/java/a/D.java": "package a;\npublic class D {\n    public void view(Object ch) {\n"
                                  "        var s = CartGrpc.newBlockingStub(ch);\n        s.addItem(null);\n    }\n}\n",
        "py/app/__init__.py": "",
        "py/app/c.py": "import cart_pb2_grpc\n\n\nclass C:\n    def __init__(self, ch):\n"
                       "        self._inner = cart_pb2_grpc.CartStub(ch)\n\n    @property\n    def _stub(self):\n"
                       "        return self._inner\n\n    def view(self):\n        return self._stub.GetCart(1)\n",
        "go/a/go.mod": "module a\n",
        "go/a/main.go": "package main\n\nfunc main() {\n\tresp, err := pb.NewCartClient(conn).\n\t\tGetCart(ctx, nil)\n}\n",
    })
    s = structure.build(repo)
    got = sorted((f, tuple(g["keys"])) for f, ff in s["facts"].items() for g in ff.get("grpc", []) if g["side"] == "client")
    assert ("src/main/java/a/D.java", ("grpc cart.v1.Cart/AddItem",)) in got
    assert ("py/app/c.py", ("grpc cart.v1.Cart/GetCart",)) in got
    assert ("go/a/main.go", ("grpc cart.v1.Cart/GetCart", "grpc cart.v1.Cart/AddItem")) in got   # the stub's end


def test_a_factory_another_services_stub_and_a_class_named_like_a_service(make_repo):
    """A library's stub factory gives way to the calls on what it returns; a value bound to another service's stub
    is that service's; `new Vuex.Store()` in a file importing no gRPC is no Store client."""
    repo = make_repo({
        "proto/cart.proto": CART_PROTO, "proto/store.proto": STORE_PROTO,
        "lib/go.mod": "module lib\n",
        "lib/cart.go": "package lib\n\nfunc NewCartClient(conn *grpc.ClientConn) pb.CartClient {\n"
                       "\treturn pb.NewCartClient(conn)\n}\n",
        "web/go.mod": "module web\n",
        "web/main.go": "package main\n\nfunc view(ctx context.Context, c pb.CartClient) {\n\tc.GetCart(ctx, nil)\n}\n",
        "py/app/__init__.py": "",
        "py/app/m.py": "import cart_pb2_grpc\nimport store_pb2_grpc\n\n\nclass C:\n    def __init__(self, ch):\n"
                       "        self.cart_stub = cart_pb2_grpc.CartStub(ch)\n        self.store_stub = store_pb2_grpc.StoreStub(ch)\n\n"
                       "    def view(self):\n        return self.store_stub.Check(1)\n",
        "package.json": '{"name": "ui"}\n',
        "ui/store.js": "const store = new Vuex.Store({state: {}})\nexport function read() { return store.get('k') }\n",
    })
    s = structure.build(repo)
    got = sorted((f, tuple(g["keys"])) for f, ff in s["facts"].items() for g in ff.get("grpc", []) if g["side"] == "client")
    assert ("web/main.go", ("grpc cart.v1.Cart/GetCart",)) in got
    assert not any(f in ("lib/cart.go", "ui/store.js") for f, _ in got), got
    # the Store call is Store's; the Cart stub, called nowhere the scan sees in its module, keeps its own end
    assert sorted(k for f, k in got if f == "py/app/m.py") == [
        ("grpc cart.v1.Cart/GetCart", "grpc cart.v1.Cart/AddItem"), ("grpc store.v1.Store/Check",)]


def test_a_helper_returning_the_stub_a_plain_constructor_and_a_binding_over_lines(make_repo):
    """The repo's helper returning this service's stub is no other service's; a deployable's `NewServer` is no
    stub factory, so its module keeps its stub end; a binding split over lines still binds the stub."""
    repo = make_repo({
        "proto/cart.proto": CART_PROTO,
        "pom.xml": "<project/>\n",
        "src/main/java/a/D.java": "package a;\nimport io.grpc.ManagedChannel;\npublic class D {\n"
                                  "    CartGrpc.CartBlockingStub opStub(String op) {\n        var base = CartGrpc.newBlockingStub(ch);\n"
                                  "        return base;\n    }\n"
                                  "    public void view(String op) {\n        var stubWithOp = opStub(op);\n        stubWithOp.getCart(null);\n    }\n}\n",
        "srv/go.mod": "module srv\n",
        "srv/main.go": "package main\n\nfunc NewServer(conn *grpc.ClientConn) *Server {\n"
                       "\treturn &Server{cart: pb.NewCartClient(conn)}\n}\n",
        "web/go.mod": "module web\n",
        "web/main.go": "package main\n\nfunc view(ctx context.Context) {\n\tc :=\n\t\tpb.NewCartClient(conn)\n"
                       "\tc.AddItem(ctx, nil)\n}\n",
    })
    s = structure.build(repo)
    got = sorted((f, tuple(g["keys"])) for f, ff in s["facts"].items() for g in ff.get("grpc", []) if g["side"] == "client")
    assert ("src/main/java/a/D.java", ("grpc cart.v1.Cart/GetCart",)) in got
    assert ("srv/main.go", ("grpc cart.v1.Cart/GetCart", "grpc cart.v1.Cart/AddItem")) in got
    assert ("web/main.go", ("grpc cart.v1.Cart/AddItem",)) in got


def test_a_stub_of_a_service_the_repo_has_no_proto_of_is_another_services(make_repo):
    repo = make_repo({
        "proto/cart.proto": CART_PROTO,
        "py/app/__init__.py": "",
        "py/app/c.py": "import cart_pb2_grpc\nimport legacy_pb2_grpc\n\n\nclass C:\n    def __init__(self, ch):\n"
                       "        self.cart_stub = cart_pb2_grpc.CartStub(ch)\n"
                       "        self.legacy_stub = legacy_pb2_grpc.LegacyCartStub(ch)\n\n"
                       "    def view(self):\n        return self.legacy_stub.GetCart(1)\n",
    })
    s = structure.build(repo)
    got = [tuple(g["keys"]) for g in s["facts"]["py/app/c.py"].get("grpc", []) if g["side"] == "client" and g["keys"]]
    assert got == [("grpc cart.v1.Cart/GetCart", "grpc cart.v1.Cart/AddItem")]


def test_a_repo_written_wrapper_of_the_stub_is_no_other_services(make_repo):
    repo = make_repo({
        "proto/cart.proto": CART_PROTO,
        "py/app/__init__.py": "",
        "py/app/c.py": "import cart_pb2_grpc\n\n\nclass RetryingStub:\n    pass\n\n\nclass C:\n    def __init__(self, ch):\n"
                       "        self.cart_stub = cart_pb2_grpc.CartStub(ch)\n        self.stub = RetryingStub(self.cart_stub)\n\n"
                       "    def view(self):\n        return self.stub.GetCart(1)\n",
    })
    s = structure.build(repo)
    got = [tuple(g["keys"]) for g in s["facts"]["py/app/c.py"].get("grpc", []) if g["side"] == "client" and g["keys"]]
    assert got == [("grpc cart.v1.Cart/GetCart",)]


def test_a_class_the_repo_writes_does_not_hide_a_qualified_generated_stub(make_repo):
    """A repo class named like a generated stub (a fake, a wrapper) is the repo's only where its bare name is
    used; `pb.NewCartClient(conn)` and `legacy_pb2_grpc.LegacyCartStub(ch)` stay the generated ones."""
    repo = make_repo({
        "proto/cart.proto": CART_PROTO,
        "httpc/go.mod": "module httpc\n",
        "httpc/c.go": "package httpc\n\ntype CartClient struct{}\n",
        "own/go.mod": "module own\n",
        "own/cartc/c.go": "package cartc\n\ntype Cart struct{}\n\ntype CartClient struct{\n\tinner pb.CartClient\n}\n\n"
                          "func (c *CartClient) Get(ctx context.Context) {\n\tc.inner.GetCart(ctx, nil)\n}\n",
        "own/web/v.go": "package web\n\nfunc view(ctx context.Context, cc *cartc.CartClient) {\n\tcc.GetCart(ctx)\n}\n",
        "own/cart-v2/c.go": "package cartv\n\ntype CartStub struct{}\n",
        "own/web/w.go": "package web\n\nfunc edit(ctx context.Context, cs *cartv.CartStub) {\n\tcs.AddItem(ctx)\n}\n",
        "Web/Web.csproj": "<Project/>\n",
        "Web/Cart/CartClient.cs": "namespace Web.Shop;\npublic class CartClient {}\n",
        "Web/Pages/View.cs": "namespace Web.Pages;\npublic class View {\n    public void Show(object ch) {\n"
                             "        var client = new Cart.CartClient(ch);\n        client.GetCart(null);\n    }\n}\n",
        "web/go.mod": "module web\n",
        "web/cart.go": "package main\n\nfunc view(ctx context.Context) {\n\tc := pb.NewCartClient(conn)\n"
                       "\tc.GetCart(ctx, nil)\n}\n",
        "py/app/__init__.py": "",
        "py/app/fakes.py": "class LegacyCartStub:\n    pass\n",
        "py/app/doubles/__init__.py": "class CartStub:\n    pass\n\n\nclass Outer:\n    class CartStub:\n        pass\n",
        "py/app/f.py": "from app import doubles\n\n\nclass F:\n    def __init__(self, ch):\n"
                       "        self.fk = doubles.Outer.CartStub(ch)\n\n    def view(self):\n        return self.fk.GetCart(1)\n",
        "py/app/d.py": "from app import doubles\n\n\nclass D:\n    def __init__(self, ch):\n"
                       "        self.fk = doubles.CartStub(ch)\n\n    def view(self):\n        return self.fk.GetCart(1)\n",
        "package.json": '{"name": "ui"}\n',
        "src/wrappers/index.ts": "export class CartClient {}\n",
        "py/app/index.py": "class CartStub:\n    pass\n",
        "py/app/e.py": "from app import index\n\n\nclass E:\n    def __init__(self, ch):\n"
                       "        self.fk = index.CartStub(ch)\n\n    def view(self):\n        return self.fk.GetCart(1)\n",
        "pom.xml": "<project/>\n",
        "src/main/java/com/acme/index/CartClient.java": "package com.acme.index;\npublic class CartClient {}\n",
        "src/main/java/com/acme/View.java": "package com.acme;\npublic class View {\n    public void show(Object ch) {\n"
                                            "        var c = new com.acme.index.CartClient(ch);\n        c.getCart(null);\n    }\n}\n",
        "src/app.ts": "import * as wrappers from './wrappers'\n\nexport function view() {\n"
                      "  const fk = new wrappers.CartClient()\n  return fk.getCart({})\n}\n",
        "py/app/c.py": "import cart_pb2_grpc\nimport legacy_pb2_grpc\n\n\nclass C:\n    def __init__(self, ch):\n"
                       "        self.cart_stub = cart_pb2_grpc.CartStub(ch)\n"
                       "        self.legacy_stub = legacy_pb2_grpc.LegacyCartStub(ch)\n\n"
                       "    def view(self):\n        return self.legacy_stub.GetCart(1)\n",
    })
    s = structure.build(repo)
    keys = lambda f: [tuple(g["keys"]) for g in s["facts"][f].get("grpc", []) if g["side"] == "client" and g["keys"]]
    assert keys("web/cart.go") == [("grpc cart.v1.Cart/GetCart",)]
    # a package's or a barrel's own class makes no request
    assert ("grpc cart.v1.Cart/GetCart",) not in keys("py/app/d.py") + keys("src/app.ts") + keys("py/app/f.py")
    # a module or package that is only named `index` stays itself
    assert ("grpc cart.v1.Cart/GetCart",) not in keys("py/app/e.py") + keys("src/main/java/com/acme/View.java")
    assert keys("own/web/w.go") == []   # a Go package named apart from its folder
    assert keys("Web/Pages/View.cs") == [("grpc cart.v1.Cart/GetCart",)]   # the folder of a C# class is no qualifier
    assert keys("own/web/v.go") == [] and keys("own/cartc/c.go") == [("grpc cart.v1.Cart/GetCart",)]   # the wrapper's
    assert keys("py/app/c.py") == [("grpc cart.v1.Cart/GetCart", "grpc cart.v1.Cart/AddItem")]


def test_a_barrel_in_a_folder_of_its_own_name_is_the_repos(make_repo):
    repo = make_repo({
        "proto/cart.proto": CART_PROTO,
        "web/go.mod": "module web\n",
        "web/cart.go": "package main\n\nfunc view(ctx context.Context) {\n\tc := pb.NewCartClient(conn)\n"
                       "\tc.GetCart(ctx, nil)\n}\n",
        "package.json": '{"name": "ui"}\n',
        "src/index/index.ts": "export class CartClient {}\n",
        "src/b.ts": "import * as index from './index'\n\nexport function view() {\n"
                    "  const fk = new index.CartClient()\n  return fk.getCart({})\n}\n",
        "lib/index/wrappers/index.ts": "export class CartStub {}\n",
        "lib/c.ts": "import * as wrappers from './index/wrappers'\n\nexport function view() {\n"
                    "  const fk = new wrappers.CartStub()\n  return fk.getCart({})\n}\n",
    })
    s = structure.build(repo)
    for f in ("src/b.ts", "lib/c.ts"):
        assert not [g for g in s["facts"][f].get("grpc", []) if g["side"] == "client" and len(g["keys"]) == 1], f
