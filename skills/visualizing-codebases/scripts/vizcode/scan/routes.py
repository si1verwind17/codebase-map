"""Framework adapters: turn framework idioms into inbound routes deterministically."""
from __future__ import annotations

import re

# --- FastAPI -------------------------------------------------------------
FASTAPI_DECORATOR = re.compile(
    r"^@(\w+)\.(get|post|put|delete|patch|websocket)\(\s*(?:path\s*=\s*)?[rRuU]?[\"']([^\"']*)[\"']")
# a router or app: FastAPI's own, or a router class of the repo's (`AppRouter(APIRouter)`), named `*Router`
FASTAPI_OWNER = re.compile(r"^[ \t]*(\w+)[ \t]*(?::[ \t]*[\w.\[\]]+[ \t]*)?=\s*(?:[\w.]*\.)?(?:FastAPI|\w*Router)\(", re.M)
FASTAPI_INCLUDE = re.compile(r"(\w+)\.include_router\(\s*([\w.]+)")
PREFIX_KW = re.compile(r"\bprefix\s*=\s*[rRuU]?[\"']([^\"']*)[\"']")


def _call_args(src: str, at: int) -> str:
    """The text inside the call whose `(` is at `at`, brackets balanced (arguments may hold calls; a bracket in a
    string does not count)."""
    depth, quote, i = 0, None, at
    while i < len(src):
        ch = src[i]
        if quote:
            i += 2 if ch == "\\" else 1
            quote = None if ch == quote else quote
            continue
        if ch in "\"'":
            quote = ch
        depth += ch in "([{"
        depth -= ch in ")]}"
        if depth == 0:
            return src[at + 1:i]
        i += 1
    return src[at + 1:]


def fastapi_decorator(text: str) -> tuple[str, str, str] | None:
    m = FASTAPI_DECORATOR.match(text.strip())
    if not m:
        return None
    method = "WS" if m.group(2) == "websocket" else m.group(2).upper()
    return m.group(1), method, m.group(3)


def fastapi_includes(src: str) -> list[dict]:
    """include_router calls: the app or router including, the router expression included, and the prefix added."""
    out = []
    for m in FASTAPI_INCLUDE.finditer(src):
        p = PREFIX_KW.search(_call_args(src, src.index("(", m.start())))
        out.append({"app": m.group(1), "router": m.group(2), "prefix": p.group(1) if p else "",
                    "line": src.count("\n", 0, m.start()) + 1})
    return out


def fastapi_prefixes(src: str) -> dict[str, str]:
    """Router or app variable -> the prefix its constructor sets ("" when none)."""
    out = {}
    for m in FASTAPI_OWNER.finditer(src):
        p = PREFIX_KW.search(_call_args(src, m.end() - 1))
        out[m.group(1)] = p.group(1) if p else ""
    return out


# --- tapir (Scala) -------------------------------------------------------
TAPIR_USE_START = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*(?![\w(]))*")
TAPIR_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*(?![\w(]))*")
TAPIR_LIT = re.compile(r'^"([^"]*)"$')
TAPIR_CAP = re.compile(r'^path\[[^\]]*\](?:\("([^"]*)"\))?$')
HTTP_METHODS = {"get", "post", "put", "delete", "patch"}
# collection and Option calls: on a value named like an endpoint (`filters.contains(..)`) they mean no tapir chain
NOT_TAPIR = {"contains", "exists", "forall", "getOrElse", "orElse", "isDefined", "isEmpty", "nonEmpty", "filter",
             "find", "foreach", "fold", "flatMap", "headOption", "head", "toList", "toSet", "toSeq", "size", "length",
             "mkString", "startsWith", "endsWith", "equals", "split", "trim", "collect", "count", "apply"}
ROOT = "endpoint"   # tapir's own root endpoint: no path segments
COMMENT = re.compile(r'("(?:\\.|[^"\\\n])*")|//[^\n]*|/\*[\s\S]*?\*/')   # a string is kept, a comment dropped


def _uncommented(text: str) -> str:
    return COMMENT.sub(lambda m: m.group(1) or " ", text)
# endpoint builder steps that add no path: a prefix may carry them (a shared base with its errors and security)
TAPIR_STEPS = {"in", "out", "errorOut", "errorOutVariant", "errorOutVariants", "errorOutEither", "securityIn",
               "prependIn", "prependSecurityIn", "mapIn", "mapOut", "mapErrorOut", "tag", "tags", "name", "summary",
               "description", "deprecated", "attribute", "info"}


def _chain(text: str, bare: frozenset | set = frozenset()) -> tuple[list[tuple[str, str | None]], int]:
    """`.name(args)` steps at the start of whitespace-free `text` (args with balanced brackets), plus bare
    `.name` steps for names in `bare` (arg None), and where the chain stops."""
    steps, i = [], 0
    while True:
        m = re.match(r"\.([A-Za-z_]\w*)(\(?)", text[i:])
        if not m or (not m.group(2) and m.group(1) not in bare):
            return steps, i
        if not m.group(2):
            steps.append((m.group(1), None))
            i += m.end()
            continue
        j, depth, quoted = i + m.end(), 1, False
        while j < len(text) and depth:
            ch = text[j]
            if ch == '"':
                quoted = not quoted
            elif not quoted:
                depth += ch in "([{"
                depth -= ch in ")]}"
            j += 1
        if depth:
            return steps, i
        steps.append((m.group(1), text[i + m.end():j - 1]))
        i = j


def _path_segs(arg: str, consts: dict[str, str] | None = None) -> list[str] | None:
    """Segments of a path input: `"v1" / "quote"`, `path[UUID]("id") / "cancel"`, a string constant of the file
    (`UserPath / "login"`); None for anything else (`query[..]`, `jsonBody[..]`, headers)."""
    parts, depth, cur = [], 0, ""
    for ch in arg:
        if ch == "/" and depth == 0 and cur.count('"') % 2 == 0:
            parts.append(cur)
            cur = ""
            continue
        depth += ch in "([{"
        depth -= ch in ")]}"
        cur += ch
    parts.append(cur)
    out = []
    for p in parts:
        if (m := TAPIR_LIT.match(p)) is not None:
            out += [s for s in m.group(1).split("/") if s]
        elif consts and p in consts:
            out += [s for s in consts[p].split("/") if s]
        elif (m := TAPIR_CAP.match(p)) is not None:
            out.append("{" + (m.group(1) or "param") + "}")
        else:
            return None
    return out


def tapir_val(scope: list[str], name: str, value_text: str, key: str | None = None) -> tuple[str, dict] | None:
    """A `val name = base.in("a" / "b")` endpoint prefix, keyed by its qualified name (or `key`: an object's own
    name for its `def apply() = prefix`). Steps that add no path (an error output, headers, a security input) keep
    it a prefix. A val that already picks an HTTP method is an endpoint, not a prefix: it is read as a body by
    tapir_uses."""
    v = re.sub(r"\s+", "", _uncommented(value_text))
    m = TAPIR_DOTTED.match(v)
    if not m or m.group(0).rsplit(".", 1)[-1] in HTTP_METHODS:
        return None
    steps, stop = _chain(v[m.end():])
    if m.end() + stop != len(v):
        return None
    segs = []
    for step, arg in steps:
        if step not in TAPIR_STEPS:
            return None
        if step == "in" and (got := _path_segs(arg)) is not None:
            segs += got
    return key or ".".join(scope + [name]), {"base": m.group(0), "segs": segs, "scope": scope}


def resolve_tapir(vals: dict[str, dict]) -> dict[str, list[str]]:
    """Qualified val name -> full path segments, for vals rooted at tapir's `endpoint`."""
    cache: dict[str, list[str] | None] = {}

    def res(q: str, seen: frozenset) -> list[str] | None:
        if q in cache:
            return cache[q]
        v = vals[q]
        out = None
        if v["base"] == ROOT:
            out = list(v["segs"])
        else:
            scoped = [c for i in range(len(v["scope"]), -1, -1)
                      if (c := ".".join(v["scope"][:i] + [v["base"]])) in vals]
            # a base another object defines (`baseEndpoint` from an imported `Http`): the one val of that name
            elsewhere = [q2 for q2 in vals if q2.endswith("." + v["base"])]
            cand = scoped[0] if scoped else (elsewhere[0] if len(elsewhere) == 1 else None)
            if cand is not None and cand not in seen:
                parent = res(cand, seen | {cand})
                out = None if parent is None else parent + v["segs"]
        cache[q] = out
        return out

    return {q: p for q in vals if (p := res(q, frozenset({q}))) is not None}


def _known(dotted: str, resolved: dict[str, list[str]]) -> tuple[list[str], str | None] | None:
    """`Base.V1.x.get` -> (segments of Base.V1.x, "get"): the longest known prefix, then at most one method."""
    parts = dotted.split(".")
    for k in range(len(parts), 0, -1):
        rest = parts[k:]
        if len(rest) > 1 or (rest and rest[0] not in HTTP_METHODS):
            continue
        prefix = ".".join(parts[:k])
        segs = resolved.get(prefix)
        if segs is None:
            cands = [q for q in resolved if q.endswith("." + prefix)]
            segs = resolved[cands[0]] if len(cands) == 1 else None
        if segs is not None:
            return segs, (rest[0] if rest else None)
    return None


def tapir_uses(body_text: str, resolved: dict[str, list[str]],
               consts: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """(METHOD, /path) for each endpoint chain on a known prefix in a body: `<prefix>.get.in(..)`,
    `<prefix>.in(..).get.out(..)`, or a whole body that is one finished endpoint with no method (tapir's
    default, GET). Pass `endpoint: []` in `resolved` when the file imports tapir."""
    text = re.sub(r"\s+", " ", _uncommented(body_text).strip())   # one space first, so two words never join
    text = re.sub(r" (?=\W)|(?<=\W) ", "", text)
    text = re.sub(r"(?<=\w)\(\)", "", re.sub(r"\.apply\(\)", "", text))   # `Base.V1()`: a prefix a method returns
    text = re.sub(r"(?<=\w)\[[\w.,\[\]]+\](?=\.)", "", text)   # `secureEndpoint[ApiKey].get`: a generic prefix
    out = []
    for m in TAPIR_USE_START.finditer(text):
        hit = _known(m.group(0), resolved)
        if hit is None:
            continue
        segs, method = hit
        steps, stop = _chain(text[m.end():], bare=HTTP_METHODS)
        extra, finished, ok = [], False, True
        for step, arg in steps:
            if arg is None:                     # `.get` after the inputs
                method = method or step
            elif step in HTTP_METHODS:          # `x.get("k")`: a lookup, not tapir
                ok = False
                break
            elif step == "in" and (got := _path_segs(arg, consts)) is not None:
                extra += got
            elif method is None and step in NOT_TAPIR:   # `filters.contains(..)`: a value named like an endpoint
                ok = False
                break
            else:
                finished = True                 # body, query, output or error: the endpoint is being built
        if not ok:
            continue
        if method is None:
            whole = m.start() == 0 and m.end() + stop == len(text)
            if not (whole and finished):
                continue
            method = "get"
        out.append((method.upper(), "/" + "/".join(segs + extra)))
    return out

