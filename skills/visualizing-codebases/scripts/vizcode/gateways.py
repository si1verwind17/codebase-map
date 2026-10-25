"""Gateway routes: the path prefixes a reverse proxy or API gateway config sends on, and where.

Read line by line (a template's `${VAR}` breaks a YAML or JSON parser): nginx `location /x/ { proxy_pass http://h/; }`,
Spring Cloud Gateway routes (`uri: lb://svc` with `Path=/x/**` and `StripPrefix=N`, YAML or properties), Envoy
`match: { prefix: "/x/" }` with `route: { cluster: c, prefix_rewrite: "/" }` (the cluster's address when the file
gives one), YARP `ReverseProxy` routes and clusters in appsettings JSON. Each is `{file, line, prefix, target,
rewrite, kind}`: `rewrite` is what replaces the prefix on the way (`/` when the proxy strips it, None when the path
goes on whole). A target keeps no user name or password.
"""
from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

NGINX_FILE = re.compile(r"(?:^|/)(?:nginx[\w.-]*|[\w.-]+\.conf(?:\.template)?|[\w.-]+\.nginx)$")
NGINX_LOCATION = re.compile(r"^\s*location\s+(?:(?:=|\^~)\s+)?(/[^\s{]*)\s*\{")
NGINX_PASS = re.compile(r"^\s*(?:proxy_pass|grpc_pass)\s+(?:grpcs?|https?)://([^\s;]+)\s*;")
SPRING_FILE = re.compile(r"(?:^|/)(?:application|bootstrap)[\w-]*\.(?:ya?ml|properties)$")
SPRING_URI = re.compile(r"^(\s*)(?:-\s+)?uri\s*:\s*[\"']?(lb|https?|wss?)://([^\s\"']+)[\"']?\s*(?:#.*)?$")
SPRING_ID = re.compile(r"^(\s*)-\s+id\s*:")
SPRING_PATH = re.compile(r"\bPath\s*=\s*([^\s,'\"]+(?:\s*,\s*[^\s,'\"]+)*)")
SPRING_STRIP = re.compile(r"\bStripPrefix\s*=\s*(\d+)")
SPRING_PROP = re.compile(r"^\s*spring\.cloud\.gateway(?:\.server\.webflux)?\.routes\[(\d+)\]\.(uri|predicates\[\d+\]|filters\[\d+\])"
                         r"\s*[=:]\s*(.+?)\s*$")
ENVOY_PREFIX = re.compile(r"""\bprefix\s*:\s*["']?(/[^"'\s,}]*)["']?""")
ENVOY_CLUSTER = re.compile(r"""\bcluster\s*:\s*["']?([\w.\-]+)""")
ENVOY_REWRITE = re.compile(r"""\bprefix_rewrite\s*:\s*["']([^"']*)["']""")
ENVOY_NAME = re.compile(r"""^(\s*)-\s+name\s*:\s*["']?([\w.\-]+)""")
ENVOY_ADDRESS = re.compile(r"""\baddress\s*:\s*["']?([\w.\-${}]+)""")
ENVOY_PORT = re.compile(r"""\bport_value\s*:\s*["']?([\w${}]+)""")
YARP_FILE = re.compile(r"(?:^|/)appsettings[\w.-]*\.json$")


def _bare(url: str) -> str:
    """An address after `scheme://` with any user name and password dropped: whatever comes before its last `@` (a
    password may hold `@` or `/`), so none of it is ever printed; a query or fragment (`?token=..`) goes too."""
    return re.split(r"[?#]", url.rpartition("@")[2], maxsplit=1)[0]


def _host(url: str) -> str:
    """`user:pw@cart:8080/api` -> `cart:8080`; the rest of the address is the rewrite (_rest)."""
    return _bare(url).split("/", 1)[0]


def _rest(url: str) -> str | None:
    bare = _bare(url)
    return "/" + bare.split("/", 1)[1] if "/" in bare else None


def _nginx(f: str, lines: list[str]) -> list[dict]:
    out, stack = [], []   # open blocks: the location (prefix, line) each opened, or None
    for i, raw in enumerate(lines, 1):
        line = raw.split("#", 1)[0]
        braces = re.sub(r"\$\{[^}]*\}|\"[^\"]*\"|'[^']*'", "", line)   # a template's `${VAR}`, a quoted string
        if m := NGINX_LOCATION.match(line):
            stack.append((m.group(1), i))
        elif braces.rstrip().endswith("{"):
            stack.append(None)
        if m := NGINX_PASS.match(line):
            where = next((x for x in reversed(stack) if x), None)
            if where is not None:
                out.append({"file": f, "line": where[1], "prefix": where[0], "target": _host(m.group(1)),
                            "rewrite": _rest(m.group(1)), "kind": "nginx"})
        for _ in range(braces.count("}")):
            if stack:
                stack.pop()
    return out


def _spring(f: str, lines: list[str]) -> list[dict]:
    routes: list[dict] = []
    props: dict[str, dict] = {}   # `spring.cloud.gateway.routes[0].uri=..`: by index
    cur = None
    for i, line in enumerate(lines, 1):
        if m := SPRING_PROP.match(line):
            cur = props.setdefault(m.group(1), {"line": i, "target": None, "paths": [], "strip": None})
            line = m.group(3) if m.group(2) != "uri" else f"uri: {m.group(3)}"
        elif SPRING_ID.match(line):
            cur = {"line": i, "target": None, "paths": [], "strip": None}
            routes.append(cur)
        if m := SPRING_URI.match(line):
            if cur is None or (cur["target"] is not None and cur not in props.values()):
                cur = {"line": i, "target": None, "paths": [], "strip": None}
                routes.append(cur)
            cur["target"] = _host(m.group(3))
        elif cur is not None:
            if p := SPRING_PATH.search(line):
                cur["paths"] += [x.strip() for x in p.group(1).split(",")]
            if s := SPRING_STRIP.search(line):
                cur["strip"] = int(s.group(1))
    out = []
    for r in routes + list(props.values()):
        for path in r["paths"] if r["target"] else []:
            prefix = re.sub(r"/\*\*?$", "", path) or "/"
            segs = [x for x in prefix.split("/") if x]
            rewrite = None if not r["strip"] else "/" + "/".join(segs[r["strip"]:])
            out.append({"file": f, "line": r["line"], "prefix": prefix, "target": r["target"], "rewrite": rewrite,
                        "kind": "spring-gateway"})
    return out


def _envoy(f: str, lines: list[str]) -> list[dict]:
    text = "\n".join(lines)
    if "route_config" not in text and "virtual_hosts" not in text:
        return []
    addresses: dict[str, str] = {}
    for i, line in enumerate(lines):   # a cluster's first address and port
        if (m := ENVOY_NAME.match(line)) and m.group(2) not in addresses:
            for nxt in lines[i + 1:i + 40]:
                if ENVOY_NAME.match(nxt) and len(ENVOY_NAME.match(nxt).group(1)) <= len(m.group(1)):
                    break
                if a := ENVOY_ADDRESS.search(nxt):
                    j = lines.index(nxt, i)
                    port = next((p.group(1) for x in lines[j:j + 4] if (p := ENVOY_PORT.search(x))), None)
                    addresses[m.group(2)] = a.group(1) + (f":{port}" if port else "")
                    break
    out = []
    for i, line in enumerate(lines):
        if "match" not in line and not (i and "match" in lines[i - 1]):
            continue
        if not (p := ENVOY_PREFIX.search(line)):
            continue
        cluster = rewrite = None
        for nxt in lines[i:i + 8]:
            if nxt is not line and "match" in nxt:
                break
            cluster = cluster or ((c := ENVOY_CLUSTER.search(nxt)) and c.group(1))
            rewrite = rewrite or ((w := ENVOY_REWRITE.search(nxt)) and w.group(1))
        if cluster:
            out.append({"file": f, "line": i + 1, "prefix": p.group(1), "target": addresses.get(cluster, cluster),
                        "rewrite": rewrite, "kind": "envoy"})
    return out


def _uncommented_json(text: str) -> str:
    """JSON with a BOM and `//` or `/* */` comments (as appsettings files have them) made plain, strings kept."""
    return re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', lambda m: m.group() if m.group().startswith('"') else "",
                  text.lstrip("\ufeff"), flags=re.S)


def _yarp(f: str, text: str) -> list[dict]:
    if "ReverseProxy" not in text:
        return []
    try:
        doc = json.loads(_uncommented_json(text))
    except ValueError:
        return []
    proxy = doc.get("ReverseProxy") if isinstance(doc, dict) else None
    if not isinstance(proxy, dict):
        return []
    obj = lambda x: x if isinstance(x, dict) else {}
    lines = text.split("\n")
    clusters = {}
    for cid, c in obj(proxy.get("Clusters")).items():
        dests = [obj(d).get("Address") for d in obj(obj(c).get("Destinations")).values()]
        clusters[cid] = next((_host(re.sub(r"^\w+://", "", d)) for d in dests if isinstance(d, str)), cid)
    routes_at = next((i for i, x in enumerate(lines) if '"Routes"' in x), 0)
    out = []
    for rid, r in obj(proxy.get("Routes")).items():
        path = obj(obj(r).get("Match")).get("Path")
        if not isinstance(path, str):
            continue
        line = next((i for i, x in enumerate(lines[routes_at:], routes_at + 1) if f'"{rid}"' in x), routes_at + 1)
        prefix = re.sub(r"/\{\*\*?[^}]*\}$", "", path) or "/"
        removes = any("PathRemovePrefix" in t for t in r.get("Transforms") or [] if isinstance(t, dict))
        cid = r.get("ClusterId") if isinstance(r.get("ClusterId"), str) else None
        out.append({"file": f, "line": line, "prefix": prefix, "target": clusters.get(cid, cid),
                    "rewrite": "/" if removes else None, "kind": "yarp"})
    return out


def read(tree: list[str], skip, text) -> list[dict]:
    """Every gateway route of the tree's config files; `skip(path)`: excluded; `text(path)`: the file's text or None."""
    out = []
    for f in tree:
        name = PurePosixPath(f).name
        kinds = [k for k, rx in (("nginx", NGINX_FILE), ("spring", SPRING_FILE), ("yarp", YARP_FILE)) if rx.search(f)]
        if not kinds and name.endswith((".yaml", ".yml")):
            kinds = ["envoy"]
        if not kinds or skip(f) or (src := text(f)) is None:
            continue
        lines = src.split("\n")
        for k in kinds:
            if k == "nginx":
                out += _nginx(f, lines)
            elif k == "spring":
                out += _spring(f, lines)
            elif k == "yarp":
                out += _yarp(f, src)
        if "envoy" in kinds or "spring" in kinds and "route_config" in src:
            out += _envoy(f, lines)
    return out
