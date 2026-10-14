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
             "server_streams": True, "line": 9, "key": KEY}]}]}


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
