import pytest

from vizcode import proto, structure

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
    assert client == [{"side": "client", "service": "OccupancyFeed", "keys": [KEY],
                       "in": "sensor_gateway/app::app.uplink.OccupancyUplink#run/1", "line": 18}]
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
            "(sensor_gateway/app/uplink.py:18)") in md
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
                "Web/Client.cs": [("client", "Web::Shop.Web.Client#Go/1"), ("client", "Web::Shop.Web.Client#Wire/1")]}),
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
    assert f"- **grpc clients:** {SHOP_KEY} ← web::_root_/client.go#Place/1 (web/client.go:4)" in md
