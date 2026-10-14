"""Protocol Buffers: gRPC services and rpcs from `.proto` files, and the stubs that name them in code.

Each rpc gets the protocol key `grpc <package>.<Service>/<Rpc>` (no package: `grpc <Service>/<Rpc>`).
A client stub (`<Service>Stub`, `<Service>Grpc.stub`) or a server base (`<Service>Servicer`,
`<Service>Grpc.<Service>`, `add_<Service>Servicer_to_server`, `<Service>Grpc.bindService`) is tied
to the keys of every proto service with that name, so both ends of a call share a key. A name that
is neither generated code nor a service of a repo .proto is not an end (`createStub`, `FakeXStub`).
"""
from __future__ import annotations

import re

COMMENT = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
PACKAGE = re.compile(r"\bpackage\s+([\w.]+)\s*;")
SERVICE = re.compile(r"\bservice\s+(\w+)\s*\{")
RPC = re.compile(r"\brpc\s+(\w+)\s*\(\s*(stream\s+)?([\w.]+)\s*\)\s*returns\s*\(\s*(stream\s+)?([\w.]+)\s*\)")

CLIENT_GRPC = re.compile(r"(?:^|\.)(\w+)Grpc\.(?:stub|blockingStub|newStub|newBlockingStub|newFutureStub)$")
CLIENT_STUB = re.compile(r"(?:^|\.)(\w+?)Stub$")
SERVER_CALL = re.compile(r"(?:^|\.)add_(\w+)Servicer_to_server$|(?:^|\.)(\w+)Grpc\.bindService$")
SERVER_BASE = re.compile(r"(?:^|\.)(\w+?)Servicer$|(?:^|\.)(\w+)Grpc\.(\w+)$")


GENERATED = re.compile(r"_pb2_grpc\.|(?:^|\.)\w+Grpc\.|(?:^|\.)add_\w+Servicer_to_server$")
VENDORED = re.compile(r"(?:^|/)(?:third_party|vendor|node_modules|googleapis)/|(?:^|/)google/protobuf/")


def generated(name: str) -> bool:
    """Does a callee or base name come from grpc-generated code (`x_pb2_grpc.`, `XGrpc.`)? Other names
    count as gRPC ends only when a .proto in the repo defines the service."""
    return bool(GENERATED.search(name))


def vendored(path: str) -> bool:
    """Third-party .proto files (googleapis, well-known types, vendored copies) define no service of the repo."""
    return bool(VENDORED.search(path))


def _blank(m: re.Match) -> str:
    """Comments become spaces of the same shape, so offsets and line numbers survive."""
    return re.sub(r"[^\n]", " ", m.group(0))


def key(package: str | None, service: str, rpc: str) -> str:
    return f"grpc {package + '.' if package else ''}{service}/{rpc}"


def _body_end(src: str, start: int) -> int:
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return i
    return len(src)


def parse(text: str, rel_file: str) -> dict:
    """{file, package, services: [{name, line, rpcs: [{name, request, response, client_streams,
    server_streams, line, key}]}]}"""
    src = COMMENT.sub(_blank, text)
    pm = PACKAGE.search(src)
    package = pm.group(1) if pm else None
    line = lambda pos: src.count("\n", 0, pos) + 1  # noqa: E731
    services = []
    for sm in SERVICE.finditer(src):
        open_ = sm.end() - 1
        body = src[open_:_body_end(src, open_)]
        rpcs = []
        for rm in RPC.finditer(body):
            rpcs.append({"name": rm.group(1), "request": rm.group(3), "response": rm.group(5),
                         "client_streams": bool(rm.group(2)), "server_streams": bool(rm.group(4)),
                         "line": line(open_ + rm.start()), "key": key(package, sm.group(1), rm.group(1))})
        services.append({"name": sm.group(1), "line": line(sm.start()), "rpcs": rpcs})
    return {"file": rel_file, "package": package, "services": services}


def call_end(callee: str) -> tuple[str, str] | None:
    """('client' | 'server', service name) for a call that builds a stub or registers a servicer."""
    if m := SERVER_CALL.search(callee):
        return "server", m.group(1) or m.group(2)
    if m := CLIENT_GRPC.search(callee) or CLIENT_STUB.search(callee):
        return "client", m.group(1)
    return None


def base_end(base: str) -> str | None:
    """Service name for a class base that makes the class a gRPC server implementation."""
    m = SERVER_BASE.search(base.split("[", 1)[0])
    if not m:
        return None
    if m.group(1):
        return m.group(1)
    return m.group(2) if m.group(2) == m.group(3) else None


def describe(rpc: dict) -> str:
    req = ("stream " if rpc["client_streams"] else "") + rpc["request"]
    resp = ("stream " if rpc["server_streams"] else "") + rpc["response"]
    shape = {(True, True): "bidirectional streaming", (True, False): "client streaming",
             (False, True): "server streaming", (False, False): "unary"}[(rpc["client_streams"], rpc["server_streams"])]
    return f"rpc {rpc['name']}({req}) returns ({resp}), {shape}"
