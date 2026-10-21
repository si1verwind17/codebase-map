"""Protocol Buffers: gRPC services, rpcs and messages from `.proto` files, and the stubs that name them in code.

Each rpc gets the protocol key `grpc <package>.<Service>/<Rpc>` (no package: `grpc <Service>/<Rpc>`).
A client or server end named the way protoc's gRPC plugin names generated code in each language is tied
to the keys of every proto service with that name, so both ends of a call share a key:

| Language | Client | Server |
|---|---|---|
| Python | `<S>Stub(` | base `<S>Servicer`, `add_<S>Servicer_to_server(` |
| Java, Kotlin, Scala | `<S>Grpc.newStub(` (and the other stub factories), Kotlin `<S>GrpcKt.<S>CoroutineStub(` | base `<S>Grpc.<S>ImplBase`, Kotlin `<S>GrpcKt.<S>CoroutineImplBase`, Scala `<S>Grpc.<S>`; `<S>Grpc.bindService(` |
| Go | `New<S>Client(` | `Register<S>Server(`, a struct embedding `Unimplemented<S>Server` |
| C# | `new <S>.<S>Client(`, `AddGrpcClient<<S>.<S>Client>` | base `<S>.<S>Base`, `MapGrpcService<T>` of a class with that base |
| JavaScript, TypeScript | `new <pkg>.<S>(` in a file importing a gRPC library | `addService(<pkg>.<S>.service` |

A name that is neither generated code (`x_pb2_grpc.`, `XGrpc.`) nor a service of a repo .proto is not an end
(`createStub`, `FakeXStub`).
"""
from __future__ import annotations

import re

COMMENT = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
PACKAGE = re.compile(r"\bpackage\s+([\w.]+)\s*;")
SERVICE = re.compile(r"\bservice\s+(\w+)\s*\{")
RPC = re.compile(r"\brpc\s+(\w+)\s*\(\s*(stream\s+)?([\w.]+)\s*\)\s*returns\s*\(\s*(stream\s+)?([\w.]+)\s*\)")
BLOCK = re.compile(r"\b(message|enum)\s+(\w+)\s*\{")
FIELD = re.compile(r"(?:^|[;{])\s*(?:(repeated)\s+|(?:optional|required)\s+)?(map\s*<[^>]*>|[\w.]+)\s+(\w+)\s*=\s*\d+",
                   re.M)

# (side, pattern) in the order tried: the service name is the first group that matched
CALL_ENDS = [
    ("server", re.compile(r"(?:^|\.)add_(\w+)Servicer_to_server$|(?:^|\.)(\w+)Grpc\.bindService$"
                          r"|(?:^|\.)Register(\w+)Server$")),
    ("client", re.compile(r"(?:^|\.)(\w+)Grpc\.(?:stub|blockingStub|newStub|newBlockingStub|newFutureStub)$"
                          r"|(?:^|\.)(\w+)GrpcKt\.\2CoroutineStub$|(?:^|\.)New(\w+)Client$|(?:^|\.)(\w+)\.\4Client$")),
    ("client", re.compile(r"(?:^|\.)(\w+?)Stub$")),
]
SERVER_BASE = re.compile(r"(?:^|\.)(\w+?)Servicer$|(?:^|\.)(\w+)Grpc\.\2(?:ImplBase)?$"
                         r"|(?:^|\.)(\w+)GrpcKt\.\3CoroutineImplBase$|(?:^|\.)(\w+)\.\4Base$")
EMBEDDED_SERVER = re.compile(r"^Unimplemented(\w+)Server$")
# forms whose service is named in an argument or a type argument, found in the source text
TEXT_ENDS = [
    ("server", re.compile(r"\.addService\(\s*(?:[\w$]+\.)*([\w$]+)\.service\b")),
    ("client", re.compile(r"\bAddGrpcClient\s*<\s*(?:\w+\.)*(\w+)\.\1Client\s*>")),
    ("server-impl", re.compile(r"\bMapGrpcService\s*<\s*(?:\w+\.)*(\w+)\s*>")),
]
JS_NEW = re.compile(r"\bnew\s+(?:[\w$]+\.)+([\w$]+)\s*\(")

GENERATED = re.compile(r"_pb2_grpc\.|(?:^|\.)\w+Grpc(?:Kt)?\.|(?:^|\.)add_\w+Servicer_to_server$")
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
    server_streams, line, key}]}], messages: [{name, line, loc, fields}]}"""
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
    messages: list[dict] = []
    end = 0
    for bm in BLOCK.finditer(src):
        if bm.start() >= end:
            end = _body_end(src, bm.end() - 1)
            if bm.group(1) == "message":
                _message(src, bm, "", line, messages)
    return {"file": rel_file, "package": package, "services": services, "messages": messages}


def _message(src: str, m: re.Match, outer: str, line, out: list[dict]) -> None:
    """One message and the messages nested in it (`Outer.Inner`), in source order: {name, line, loc, fields:
    [{name, type}]}. A nested message or enum is no field; a `oneof`'s members are."""
    open_ = m.end() - 1
    close = _body_end(src, open_)
    name = outer + m.group(2)
    body, inner, end = list(src[open_:close]), [], 0
    for bm in BLOCK.finditer(src, open_ + 1, close):
        if bm.start() >= end:
            end = _body_end(src, bm.end() - 1)
            body[bm.start() - open_:end + 1 - open_] = " " * (end + 1 - bm.start())
            if bm.group(1) == "message":
                inner.append(bm)
    fields = [{"name": f.group(3), "type": ("repeated " if f.group(1) else "") + re.sub(r"\s+", "", f.group(2))}
              for f in FIELD.finditer("".join(body))]
    out.append({"name": name, "line": line(m.start()), "loc": line(close) - line(m.start()) + 1, "fields": fields})
    for bm in inner:
        _message(src, bm, name + ".", line, out)


def _first(m: re.Match) -> str:
    return next(g for g in m.groups() if g)


def call_end(callee: str) -> tuple[str, str] | None:
    """('client' | 'server', service name) for a call that builds a stub or registers a servicer."""
    for side, pattern in CALL_ENDS:
        if m := pattern.search(callee):
            return side, _first(m)
    return None


def base_end(base: str) -> str | None:
    """Service name for a class base that makes the class a gRPC server implementation."""
    m = SERVER_BASE.search(re.split(r"[\[<(]", base, maxsplit=1)[0])
    return _first(m) if m else None


def field_end(field: dict) -> str | None:
    """Service name for an embedded struct field that makes a Go struct a gRPC server implementation."""
    m = EMBEDDED_SERVER.match(field["name"])
    return m.group(1) if m and (field.get("type") or "").rsplit(".", 1)[-1].lstrip("*") == field["name"] else None


def text_ends(text: str, js: bool) -> list[tuple[str, str, int]]:
    """(side, name, offset) for the forms that name the service in an argument or a type argument; the side
    `server-impl` names the implementing class, not the service. With `js`, also `new <pkg>.<S>(`, a client when
    S is a proto service."""
    out = [(side, m.group(1), m.start()) for side, pattern in TEXT_ENDS for m in pattern.finditer(text)]
    if js:
        out += [("client", m.group(1), m.start()) for m in JS_NEW.finditer(text)]
    return sorted(out, key=lambda e: e[2])


def describe(rpc: dict) -> str:
    req = ("stream " if rpc["client_streams"] else "") + rpc["request"]
    resp = ("stream " if rpc["server_streams"] else "") + rpc["response"]
    shape = {(True, True): "bidirectional streaming", (True, False): "client streaming",
             (False, True): "server streaming", (False, False): "unary"}[(rpc["client_streams"], rpc["server_streams"])]
    return f"rpc {rpc['name']}({req}) returns ({resp}), {shape}"
