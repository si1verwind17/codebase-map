"""HTTP client calls the code makes through its own helpers, as `clients` facts (method + path) to match to routes.

A wrapper is a function, in a file that uses an HTTP client (an `http-out` import, or `fetch`), that passes one of
its own parameters into a client call (`request(method, url) { return axios.request({method, url}) }`), or into a
call to another wrapper (`get(url) { return this.request('get', url) }`). A call to a wrapper with a path literal
(`http.get(`albums/${id}`)`, `apiFetch({url: '/user', method: 'POST'})`) is a request; so is a client call with a
path literal outside any wrapper (`client.get("sessions")`). A wrapper's own calls are none. The method comes from
the wrapper's name (`get`), a verb literal (`'post'`, `method: 'POST'`), or the client call's name; else ANY.
"""
from __future__ import annotations

import re
from pathlib import Path

VERBS = ("get", "post", "put", "patch", "delete", "head")
# a client object's methods that send a request
CLIENT_CALLS = {*VERBS, "request", "fetch", "send", "exchange", "execute", "retrieve", "getForObject", "getForEntity",
                "postForObject", "postForEntity", "patchForObject",
                # C# HttpClient, Go net/http
                "GetAsync", "PostAsync", "PutAsync", "PatchAsync", "DeleteAsync", "SendAsync", "GetFromJsonAsync",
                "PostAsJsonAsync", "PutAsJsonAsync", "PatchAsJsonAsync", "GetStringAsync", "GetStreamAsync",
                "GetByteArrayAsync", "Get", "Post", "Head", "PostForm", "NewRequest", "NewRequestWithContext"}
# client types known by name, also where no import names them (C# implicit usings)
CLIENT_TYPES = {"HttpClient", "WebClient", "RestTemplate", "RestClient"}
# a name bound to a client the code makes (Go `client := &http.Client{..}`, `var c = new HttpClient()`)
BOUND_CLIENT = re.compile(r"(?:(?:self|this)\s*\.\s*)?([A-Za-z_]\w*)\s*(?::=|=)\s*&?\s*(?:new\s+)?"
                          r"(?:http\.Client|(?:[\w$]+\.)*(?:HttpClient|RestTemplate|WebClient|RestClient))\s*[{(]")
# names common on stores and caches too (`cache.Get(key)`): a request only on an imported or typed client
STRONG_ONLY = {"Get", "Post", "Head", "PostForm"}
GLOBAL_CLIENTS = {"fetch", "$fetch", "ofetch", "axios", "ky", "got"}
SELVES = {"this", "self", "cls"}
IDENT = re.compile(r"[A-Za-z_$][\w$]*")
STRING = re.compile(r"""`((?:\\.|[^`\\])*)`|"((?:\\.|[^"\\\n])*)"|'((?:\\.|[^'\\\n])*)'""")
KEYED = re.compile(r"""\b(?:url|path|uri|endpoint)\s*[:=]\s*(`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')""")
METHOD_KEY = re.compile(r"""\bmethod\s*[:=]\s*["'`]?(get|post|put|patch|delete|head)\b""", re.I)
VERB_LIT = re.compile(r"""["'`](get|post|put|patch|delete|head)["'`]""", re.I)
INTERP = re.compile(r"\$\{\s*([^}]+?)\s*\}|\$(\w+)|\{([\w.]+)\}")
PATHLIKE = re.compile(r"^[\w\-.~{}:@/]+$")
BASE_WORD = re.compile(r"(?i)url|base|host|root|origin|api|endpoint|prefix|server")
# the words of a value's name that make it an HTTP client (`httpClient`, `api`, `restTemplate`), and those that
# make it the serving side (`apiRouter`, `app`): whole words, never a substring (`restaurants`, `session`)
CLIENT_WORDS = {"client", "http", "https", "api", "rest", "axios", "fetcher", "webclient", "resttemplate", "ky"}
SERVER_WORDS = {"router", "app", "route", "routes", "server", "express", "mux", "engine"}
CAMEL = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
URL_NAME = re.compile(r"(?i)url|uri|path|endpoint|route|href")   # a parameter that carries an address
DESCRIPTOR_FILES = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".vue", ".svelte")
# a descriptor's address key: `path` is left out, the key of server route tables and API contracts
DESCRIPTOR_KEY = re.compile(r"""\b(?:url|uri|endpoint)\s*[:=]\s*(`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')""")
SERVER_KEY = re.compile(r"\b(?:handler|preHandler|controller|resolve)\s*[:(,}]")


def _path(literal: str) -> str | None:
    """A request path in the key form from a call's literal (`albums/${id}` -> /albums/{id}); None for an absolute
    URL (a URL literal fact already) or anything that is no path. A leading base placeholder (`${API_URL}/x`)
    is dropped."""
    literal = re.split(r"\?(?![^{]*\})", literal, maxsplit=1)[0]   # the query string is no part of the route
    p = INTERP.sub(lambda m: "{" + (m.group(1) or m.group(2) or m.group(3)).split(".")[-1].strip() + "}", literal)
    if (host := re.match(r"^[a-z]+://[^/]*\{[^/]*(?=/|$)", p)) is not None:
        p = p[host.end():] or "/"   # `http://${host}:8080/api/x`: another service's address, its path kept
    if "://" in p or not p or not PATHLIKE.match(p) or not any(c.isalpha() for c in p):
        return None
    segs = [s for s in p.split("/") if s]
    if not any(re.sub(r"\{[^}]*\}", "", s) for s in segs):
        return None   # `/{key}` from `f"https://{bucket}.s3../{key}"`, `%s%s`: no word of a route in it
    while segs and re.fullmatch(r"\{(\w+)\}", segs[0]) and (BASE_WORD.search(segs[0]) or segs[0][1:-1].isupper()):
        segs.pop(0)
    if segs and (glued := re.match(r"\{(\w+)\}(?=[A-Za-z])", segs[0])) and BASE_WORD.search(glued.group(1)):
        segs[0] = segs[0][glued.end():]   # `{baseUrl}items/{id}`: a base holding its own trailing slash
    return "/" + "/".join(segs) if segs else None


def _words(name: str) -> set[str]:
    return {w.lower() for w in CAMEL.findall(name)}


def _args(lines: list[str], line: int, name: str, nth: int = 0) -> str:
    """The argument text of the `nth` call to `name` on `line` (1-based), across lines until its brackets close; a
    trailing block (Kotlin `client.get { url("x") }`) is read the same way."""
    text = "\n".join(lines[line - 1:line + 6])
    hits = [m.end() for m in re.finditer(rf"(?<![\w$]){re.escape(name)}\s*(?:<[^<>()]*>)?\s*(?=[({{])", text)]
    start = hits[min(nth, len(hits) - 1)] if hits else -1
    if start < 0:
        return ""
    depth = 0
    for i in range(start, len(text)):
        depth += text[i] in "([{"
        depth -= text[i] in ")]}"
        if depth == 0:
            return text[start + 1:i]
    return text[start + 1:]


# a URL builder taking the path as an argument: `urljoin(BASE, "/x")`, `path.join(base, "x")`, `new URL("/x", base)`
URL_BUILDER = re.compile(r"""^(?:new\s+URL|(?:[\w$]+\.)*(?:urljoin|join|resolve))\s*\((.*)\)$""", re.S)
STRING_PREFIX = re.compile(r"^(?:[fFrRbBuU]{1,2}|\$@?|@\$?)(?=[\"'])")   # Python's `f"…"`, `r'…'`; C#'s `$"…"`, `@"…"`
# a format call on a literal: `"…/{}".format(x)`, Go `fmt.Sprintf("%s/x", base)`, Java `String.format("/x/%s", id)`
FORMATTED = re.compile(r"""^(?:(?P<lit>(?:[fFrRbBuU]|\$)?(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*'))\.format\s*\(.*\)"""
                       r"""|(?:fmt\.Sprintf|String\.format)\s*\(\s*(?P<fmt>"(?:\\.|[^"\\\n])*")\s*(?:,.*)?\))$""", re.S)
PRINTF = re.compile(r"%[-+ #0]*\d*(?:\.\d+)?[sdvqfx]")


def _plus_terms(arg: str) -> list[str]:
    """The `+`-joined terms of an expression, split outside brackets and strings."""
    terms, depth, quote, cur = [], 0, None, ""
    for ch in arg:
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "+" and depth == 0:
            terms.append(cur.strip())
            cur = ""
            continue
        cur += ch
    return terms + [cur.strip()]


def _literal(term: str) -> str | None:
    s = STRING.fullmatch(STRING_PREFIX.sub("", term.strip()))
    return next((x for x in s.groups() if x is not None), None) if s else None


def _address(arg: str, resolve=None, depth: int = 0) -> str | None:
    """The path an address argument spells: a string or template, a format call on one (`"/x/{}".format(i)`,
    `fmt.Sprintf("%s/x", base)`), a URL builder's literal argument, or `+`-joined terms holding a literal (a leading
    base dropped, each later value a `{name}` segment: `'/api/users/' + id` -> `/api/users/{id}`); `resolve(name)`
    gives the expression a bare name holds (a local assignment, a file constant), read the same way. None for a
    literal inside another call, a lookup or a choice (`route('name')`, `opts.get("url")`, `a ? 'x' : 'y'`), which
    names no path."""
    arg = arg.strip()
    if resolve is not None and depth < 3 and re.fullmatch(r"[A-Za-z_$][\w$.]*", arg) \
            and (held := resolve(arg)) is not None:
        return _address(held, resolve, depth + 1)
    if (fm := FORMATTED.match(arg)) is not None:
        text = PRINTF.sub("{v}", re.sub(r"\{\d*\}", "{v}", _literal(fm.group("lit") or fm.group("fmt")) or ""))
        # a placeholder before the first `/` is the base (`%s/api/x`): uppercase, so `_path` drops it
        return re.sub(r"^\{v\}(?=/)", "{BASE}", text) or None
    if (b := URL_BUILDER.match(arg)) is not None:
        lits = [x for part in _split_args(b.group(1)) if (x := _literal(part)) is not None]
        return lits[0] if len(lits) == 1 else None
    terms = _plus_terms(arg)
    if len(terms) == 1:
        return _literal(arg)
    out, seen_literal = [], False
    for i, term in enumerate(terms):
        if (lit := _literal(term)) is not None:
            out.append(lit)
            seen_literal = True
        elif i == 0 and resolve is not None and depth < 3 and (held := resolve(term)) is not None \
                and (head := _address(held, resolve, depth + 1)) is not None and head.startswith("/"):
            out.append(head)   # `API_PREFIX + "/users"`, the prefix a path constant of the file
        elif i == 0:
            continue   # the base the path is joined onto
        elif re.fullmatch(r"[\w$.()\[\]'\"]+", term) and (words := IDENT.findall(term)):   # `str(i)`, `user.id`
            out.append("${" + words[-1] + "}")
        else:
            return None
    return "".join(out) if seen_literal else None


# a file-level name bound to a string literal: `const basePath = '/api'`, `BASE = "/v1"`, `private static final
# String PATH = "/x";`, Go `const prefix = "/api"`
CONST_LINE = re.compile(r"""^\s*(?:export\s+)?(?:(?:const|let|var|val|final|static|private|public|protected|readonly|"""
                        r"""internal)\s+)*(?:[\w<>\[\],?]+\s+)?([A-Za-z_$][\w$]*)\s*(?::\s*[\w<>\[\]|]+\s*)?:?=\s*"""
                        r"""([fFrRbBuU$@]{0,2}(?:"[^"\n]*"|'[^'\n]*'|`[^`\n]*`))\s*;?\s*$""")
TEMPLATE_HEAD = re.compile(r"^\$?\{\s*([A-Za-z_$][\w$.]*)\s*\}")   # `${basePath}` (JS), `{baseUrl}` (C#, f-strings)


FIELD_WORDS = re.compile(r"\b(?:private|public|protected|internal|static|readonly)\b")
CONSTANT_NAME = re.compile(r"[A-Z][A-Z0-9_]*$")   # `BASE_URL`, `TOPIC`: a class's or object's constant


def _constants(lines: list[str]) -> dict[str, str]:
    from .stack import in_function
    """A file's names bound once to a string literal at its top, as a declared field (`private readonly string
    baseUrl = "x"`) or as a constant-cased name (`BASE = "/api"` in a class, Kotlin `const val TOPIC`): a name bound
    to two different ones, or a function's local (`final String base = ..` in a method), is left out."""
    seen: dict[str, set[str]] = {}
    for i, line in enumerate(lines):
        if (m := CONST_LINE.match(line)) is not None and (not line[:1].isspace() or (
                (CONSTANT_NAME.match(m.group(1)) or FIELD_WORDS.search(line.split("=", 1)[0])) and not in_function(lines, i))):
            seen.setdefault(m.group(1), set()).add(m.group(2))
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def _split_args(text: str) -> list[str]:
    """A call's arguments, split on commas outside brackets."""
    out, depth, cur = [], 0, ""
    for ch in text:
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return out + [cur]


def _first_arg(text: str) -> str:
    """The call's first argument as written, stripped (up to the first comma outside brackets)."""
    depth = 0
    for i, ch in enumerate(text):
        depth += ch in "([{"
        depth -= ch in ")]}"
        if ch == "," and depth == 0:
            return text[:i].strip()
    return text.strip()


def _parts(callee: str) -> list[str]:
    return [p for p in IDENT.findall(re.sub(r"\([^()]*\)", "", callee))]


def find(results: dict[str, dict], sources: dict[str, str], client_heads, new_file: str) -> None:
    """Add `clients` facts (framework `wrapper:<name>`, `client` or `descriptor`) to each file's result. `sources`: a
    file's text; `client_heads(f)`: the local names of the HTTP client libraries file f imports (empty when none);
    `new_file`: the `in` of a fact outside any method of a file with no file node yet."""
    nodes = {n["id"]: n for r in results.values() for n in r["nodes"]}
    lines = {f: t.split("\n") for f, t in sources.items()}
    heads = {f: set(client_heads(f)) for f in results}
    calls_in: dict[str, list[tuple[str, dict]]] = {}
    for f, r in results.items():
        for c in r["calls"]:
            if c.get("in") in nodes:
                calls_in.setdefault(c["in"], []).append((f, c))

    def params(m: dict) -> set[str]:
        return {w for p in (m.get("signature") or {}).get("params", []) for w in IDENT.findall(p.get("name") or "")
                if w not in SELVES}

    def stem(path: str) -> str:
        """A module's import name: the file stem, or its folder's name for an `index` file; for an import target
        its last segment (`./http`, `@/services/http`, Python `a.api`)."""
        if path in nodes_files:
            p = Path(path)
            return (p.parent.name if p.stem == "index" else p.stem).lower()
        return ([x for x in re.split(r"[./\\:@]+", path) if x] or [""])[-1].lower()

    def owner_name(m: dict) -> str:
        owner = nodes.get(m.get("parent") or "", {})
        return stem(owner.get("file") or owner.get("name", "")) if owner.get("kind") == "file" \
            else owner.get("name", "").lower()

    route_lines = {f: {x["line"] for x in r["routes"]} for f, r in results.items()}
    nodes_files = set(results)
    consts = {f: _constants(ls) for f, ls in lines.items()}
    # bound at the file's top: holds in every function of the file
    top_clients = {f: {n for x in ls if x[:1] not in " \t" and ("Client" in x or "Rest" in x)
                       for n in BOUND_CLIENT.findall(x)} for f, ls in lines.items()}
    # bound on the object in a method (`self.api = RestClient(..)` in `__init__`, `this.http = new HttpClient()` in
    # a constructor): holds for `self.api` / `this.http` in that class's methods, as (class id, name)
    methods = {}
    for n in nodes.values():
        if n["kind"] == "method" and n.get("file"):
            methods.setdefault(n["file"], []).append(n)
    object_clients: dict[str, set[tuple[str, str]]] = {}
    for f, ls in lines.items():
        for i, x in enumerate(ls, 1):
            if ("Client" in x or "Rest" in x) and re.match(r"\s*(?:self|this)\s*\.", x) and (names := BOUND_CLIENT.findall(x)):
                here = max((m for m in methods.get(f, []) if (m.get("line") or 0) <= i),
                           key=lambda m: m.get("line") or 0, default=None)
                if here is not None and here.get("parent"):
                    object_clients.setdefault(f, set()).update((here["parent"], n) for n in names)

    def resolver(f: str, c: dict):
        """A bare name's expression: its last assignment in the calling function before the call, else a file
        constant (`url := base + "/x"`, `const basePath = '/api'`)."""
        start = nodes.get(c.get("in") or "", {}).get("line") or 1

        def resolve(name: str) -> str | None:
            pat = re.compile(rf"(?<![\w$.]){re.escape(name)}\s*(?::\s*[\w<>\[\]|?]+\s*)?:?=(?!=)\s*(.+?)\s*;?\s*$")
            # bound some other way in the function (`for url in urls`, `with .. as url`, `catch (url)`, `{url} =`):
            # its value is no constant of the file
            other = re.compile(rf"\bfor\s*\(?\s*(?:(?:const|let|var|val|final)\s+)?(?:\w+\s+)?{re.escape(name)}\b"
                               rf"|\bas\s+{re.escape(name)}\b|\bcatch\s*\(\s*(?:\w+\s+)?{re.escape(name)}\b"
                               rf"|^\s*(?:(?:const|let|var|val)\s+)?[{{\[][^=\n]*(?<![\w$]){re.escape(name)}(?![\w$])[^=\n]*[}}\]]\s*=")
            for line in reversed(lines[f][max(start - 1, 0):c["line"] - 1]):
                if (m := pat.search(line)) is not None:
                    return m.group(1)
                if other.search(line):
                    return None
            return consts[f].get(name.split(".")[-1])
        return resolve

    def fold(f: str, lit: str, resolve) -> str:
        """A template whose head is a path constant (`${basePath}/cart` with basePath = '/api', `{baseUrl}items` with
        baseUrl = "api/catalog/") with it written in."""
        if (m := TEMPLATE_HEAD.match(lit)) is not None and (held := resolve(m.group(1))) is not None \
                and (head := _literal(held)) is not None and head and "://" not in head and PATHLIKE.match(head):
            rest = lit[m.end():]
            return "/" + head.strip("/") + ("/" if rest and not rest.startswith("/") else "") + rest
        return lit

    bases_of = {cid: names for r in results.values() for cid, names in r.get("bases", []) + r.get("supers", [])}
    classes_in = {}
    for n in nodes.values():
        if n["kind"] == "class" and n.get("file"):
            classes_in.setdefault(n["file"], {}).setdefault(n["name"], n["id"])

    def lineage(f: str, cid: str | None) -> list[str]:
        """A class and its bases written in the same file (`class Cart(Base)` holds what `Base.__init__` binds)."""
        out, todo = [], [cid] if cid else []
        while todo and len(out) < 16:
            k = todo.pop()
            if k not in out:
                out.append(k)
                todo += [i for b in bases_of.get(k, []) if (i := classes_in.get(f, {}).get(b.rsplit(".", 1)[-1]))]
        return out

    def typed_client(f: str, c: dict, receiver: str) -> bool:
        """The receiver is a parameter or field whose declared type is an imported client (`client: HttpClient`)."""
        m = nodes.get(c["in"], {})
        types = [p.get("type") or "" for p in (m.get("signature") or {}).get("params", []) if p.get("name") == receiver]
        owner = nodes.get(m.get("parent") or "", {})
        types += [x.get("type") or "" for x in (owner.get("fields") or []) + ((owner.get("ctor") or {}).get("params") or [])
                  if x.get("name") == receiver]   # a field, or a constructor parameter (C# `class Catalog(HttpClient h)`)
        start = m.get("line") or 1
        here = "\n".join(x for x in lines[f][max(start - 1, 0):c["line"]] if "Client" in x or "Rest" in x)
        made = {n for n in BOUND_CLIENT.findall(here)} | top_clients[f]   # in the calling function, or the file's top
        if any((k, receiver) in object_clients.get(f, ()) for k in lineage(f, m.get("parent"))):
            raw = _parts(c["callee"])
            if len(raw) > 2 and raw[0] in ("self", "this") and raw[1] == receiver:   # `self.api.get(..)`
                return True
        return receiver in made or any(set(IDENT.findall(t)) & (heads[f] | CLIENT_TYPES) for t in types)

    def client_call(f: str, c: dict) -> str | None:
        """`strong` for a call to an imported or global client, `weak` for a value only named like one, else None."""
        parts = [p for p in _parts(c["callee"]) if p not in SELVES]
        if not parts or f not in lines or c["line"] in route_lines.get(f, ()):
            return None    # a route registration is the serving side
        head, last = parts[0], parts[-1]
        receiver = parts[-2] if len(parts) > 1 else ""
        if _words(receiver) & SERVER_WORDS:
            return None
        if (heads[f] or typed_client(f, c, receiver)) and (last.lower() in CLIENT_WORDS or last.lower().endswith("client")) \
                and not last[:1].isupper():
            return "weak"   # a callable client (`this.client(url, ..)`), or a factory (`session.client("sts")`)
        if not (last in CLIENT_CALLS or (len(parts) == 1 and head in GLOBAL_CLIENTS)):
            return None   # a request call, not a client's constructor (`httpx.Client(..)`) or setting
        if head in GLOBAL_CLIENTS or head in heads[f] or typed_client(f, c, receiver):
            return "strong"
        if heads[f] and _words(receiver) & CLIENT_WORDS and last not in STRONG_ONLY:
            return "weak"
        # the app's own client class, its library not imported here, given an options object with an address
        # (`ApiClient.get({endpoint: '/x'})`)
        return "loose" if "client" in _words(receiver) else None

    def passes(text: str, mine: set[str]) -> bool:
        """The function passes its own parameter on as the address: a parameter named like one (`url`, `path`)
        anywhere in the call, or any parameter as the call's first argument. A parameter only inside a path
        literal (`get(`albums/${id}`)`) or in the body (`post('albums', {name})`) makes a request, passes no
        address on."""
        if any(URL_NAME.search(p) and re.search(rf"(?<![\w$.]){re.escape(p)}\b", text) for p in mine):
            return True
        first = _first_arg(text)
        return first in mine

    def verb_of(*hints: str | None, heads: tuple[str | None, ...] = ()) -> str | None:
        """The verb a hint says: one that is a verb (`post`) first, else the head of a client call's name in `heads`
        (`GetFromJsonAsync`, `postForObject`); a function's own name says it only whole (`getResponse(url, method)`
        is no GET, a `getPermalink` calling `client.post` is a POST)."""
        if exact := next((h.upper() for h in (*hints, *heads) if h and h.lower() in VERBS), None):
            return exact
        for h in heads:
            if h and (v := next((v for v in VERBS if h[:len(v)].lower() == v and h[len(v):][:1].isupper()), None)):
                return v.upper()
        return None

    wrappers: dict[str, dict] = {}   # method id -> {"name", "owner", "file", "verb"}
    by_name: dict[str, list[dict]] = {}

    def add(mid: str, verb: str | None) -> None:
        m = nodes[mid]
        w = {"name": m["name"], "owner": owner_name(m), "file": m.get("file") or "", "parent": m.get("parent"),
             "free": nodes.get(m.get("parent") or "", {}).get("kind") != "class", "verb": verb}
        wrappers[mid] = w
        by_name.setdefault(w["name"], []).append(w)

    def imports_of(f: str, w: dict, local: str) -> bool:
        """File f can name `local` from the wrapper's module: it imports it from there (`import { http } from
        './http'`, `* as http`, `from a.api import call`), imports the module by that name (`from a import api`),
        or sits in the same folder (a Java or Kotlin package)."""
        if Path(f).parent == Path(w["file"]).parent and Path(f).suffix == Path(w["file"]).suffix \
                and Path(f).suffix in (".java", ".kt", ".cs", ".scala", ".go"):
            return True
        mod = stem(w["file"])
        for imp in results[f]["imports"]:
            names = {*(imp.get("names") or []), *(imp.get("renames") or {}), imp.get("as")}
            if (stem(imp["target"]) == mod and local in names) or (local == mod and mod in names):
                return True
        return False

    def target(f: str, c: dict) -> dict | None:
        parts = _parts(c["callee"])
        if not parts:
            return None
        name, receiver = parts[-1], (parts[-2] if len(parts) > 1 else None)
        receiver = None if receiver in SELVES else receiver
        for w in by_name.get(name, []):
            if receiver is not None and receiver.lower() == w["owner"] and (w["file"] == f or imports_of(f, w, receiver)):
                return w
            if receiver is None and w["free"] and (w["file"] == f or imports_of(f, w, name)):
                return w
            if receiver is None and not w["free"] and nodes.get(c["in"], {}).get("parent") == w["parent"]:
                return w   # `this.request(..)` in the wrapper's own class
        return None

    for mid, sites in calls_in.items():   # a function passing its own parameter into a client call
        m, mine = nodes[mid], params(nodes[mid])
        for f, c in sites:
            if mine and client_call(f, c):
                text = _args(lines[f], c["line"], _parts(c["callee"])[-1])
                if passes(text, mine):
                    lit = VERB_LIT.search(text)
                    add(mid, verb_of(m["name"], lit.group(1) if lit else None, heads=(_parts(c["callee"])[-1],)))
                    break
    for _ in range(3):   # and one passing its parameter on to a wrapper
        grew = False
        for mid, sites in calls_in.items():
            if mid in wrappers or not (mine := params(nodes[mid])):
                continue
            for f, c in sites:
                if f in lines and (w := target(f, c)) is not None:
                    text = _args(lines[f], c["line"], w["name"])
                    if passes(text, mine):
                        lit = VERB_LIT.search(text)
                        add(mid, verb_of(nodes[mid]["name"], lit.group(1) if lit else None) or w["verb"])
                        grew = True
                        break
        if not grew:
            break

    for mid, sites in calls_in.items():   # the requests: calls to a wrapper, or client calls, with a path
        if mid in wrappers:
            continue
        seen: dict[tuple[str, int, str], int] = {}   # the nth call of a name on a line reads the nth one's text
        for f, c in sites:
            if f not in lines:
                continue
            w = target(f, c)
            how = None if w else client_call(f, c)
            if w is None and how is None:
                continue
            name = w["name"] if w else _parts(c["callee"])[-1]
            nth = seen[(f, c["line"], name)] = seen.get((f, c["line"], name), -1) + 1
            text = _args(lines[f], c["line"], name, nth)
            first = _first_arg(text)   # the address is the first argument, or a `url:` key of an options object
            lead = next((x for x in sm.groups() if x is not None), "") if (sm := STRING.fullmatch(first)) else ""
            lead = lead.upper() if lead.lower() in VERBS else None
            if lead:   # `request("POST", "/x")`: the method comes first
                text = text[text.index(first) + len(first):].lstrip(" ,\n\t")
                first = _first_arg(text)
            keyed = KEYED.search(first) if first.startswith("{") else None
            resolve = resolver(f, c)
            lit = keyed.group(1)[1:-1] if keyed else _address(first, resolve)
            if lit is None and not first and re.search(r"\.uri\s*\(", "\n".join(lines[f][c["line"] - 1:c["line"] + 5])):
                # `webClient.get().uri("/x/{id}", id).retrieve()`: the address is the chained `uri` call's
                lit = _address(_first_arg(_args(lines[f], c["line"], "uri")), resolve)
            if lit is not None:
                lit = fold(f, lit, resolve)
            path = _path(lit) if lit is not None else None
            if path is None or (how == "weak" and "/" not in lit) \
                    or (how == "loose" and not (keyed and lit.startswith("/"))):   # a key store's `get('/a')`: none
                continue   # a value only named like a client needs a path that reads as one
            method_key = METHOD_KEY.search(text)
            # a wrapper given its verb by the caller (`this.getResponse(`/items/${id}`, 'POST')`)
            passed = next((v.group(1).upper() for a in _split_args(text)[1:] if w and (v := VERB_LIT.fullmatch(a.strip()))),
                          None)   # an argument of its own, never a word inside a body (`{status: 'delete'}`)
            verb = lead or (method_key.group(1).upper() if method_key else None) or passed or (w["verb"] if w else None) \
                or verb_of(name, heads=() if w else (name,)) or ("GET" if name in ("fetch", "$fetch", "ofetch") else "ANY")
            have = results[f].setdefault("clients", [])
            same = next((x for x in have if (x["in"], x["line"], x["path"]) == (mid, c["line"], path)
                         and (x["method"] == verb or "ANY" in (x["method"], verb))), None)
            if same is not None:   # one request per call site: `get().uri(..).retrieve()` is one, its verb kept
                # (`gather(get('/x'), post('/x'))` on one line is two)
                if same["method"] == "ANY":
                    same["method"] = verb
                continue
            have.append({"method": verb, "path": path, "in": mid, "line": c["line"],
                         "framework": f"wrapper:{w['name']}" if w else "client"})
    _descriptors(results, lines, new_file)


def _descriptors(results: dict[str, dict], lines: dict[str, list[str]], new_file: str) -> None:
    """Request descriptors in JS/TS: an object literal holding both a verb `method:` and an address key (`url:`,
    `path:`, `endpoint:`) with a path literal, as handed to a generated client's `request(cfg, {..})` or returned by
    a query definition (`query: (id) => ({method: 'GET', url: ...})`). An object with a `handler` is a server's
    route (`server.route({method, path, handler})`); one a client call already read is not counted twice."""
    for f, ls in lines.items():
        if not f.endswith(DESCRIPTOR_FILES) or f not in results:
            continue
        r = results[f]
        text = "\n".join(ls)
        if "method" not in text:
            continue
        spans = [(n["line"], n["line"] + n["metrics"]["loc"] - 1, n["id"]) for n in r["nodes"] if n["kind"] == "method"]
        file_id = next((n["id"] for n in r["nodes"] if n["kind"] == "file"), new_file)
        known = {(c["path"], c["line"]) for c in r.get("clients", [])}
        routes = {x["line"] for x in r["routes"]}
        for m in DESCRIPTOR_KEY.finditer(text):
            if (found := _object_around(text, m.start())) is None or SERVER_KEY.search(found[0]) \
                    or not _handed_on(text, found[1]):
                continue
            obj = found[0]
            if not (verb := METHOD_KEY.search(obj)) or (path := _path(m.group(1)[1:-1])) is None:
                continue
            line = text.count("\n", 0, m.start()) + 1
            if line in routes or any((path, x) in known for x in range(line - 6, line + 1)):
                continue
            inside = [s for s in spans if s[0] <= line <= s[1]]
            where = max(inside, key=lambda s: s[0])[2] if inside else file_id
            r.setdefault("clients", []).append({"method": verb.group(1).upper(), "path": path, "in": where,
                                                "line": line, "framework": "descriptor"})


def _handed_on(text: str, start: int) -> bool:
    """The object literal opening at `start` is a call's argument (`request(cfg, {..})`) or what an arrow returns
    (`=> ({..})`), not an array entry or a property's value (a route table, an API contract, a serverless event)."""
    depth = 0
    for i in range(start - 1, max(-1, start - 2000), -1):
        depth += text[i] in ")]}"
        depth -= text[i] in "([{"
        if depth < 0:
            return text[i] == "(" and (bool(re.search(r"[\w$\]>)]\s*(?:<[^<>()]*>)?\s*$", text[:i]))
                                       or text[:i].rstrip().endswith("=>"))
    return False


def _object_around(text: str, at: int) -> tuple[str, int] | None:
    """The text of the innermost `{..}` around offset `at`, and where it opens (strings not parsed: a brace in one
    may mislead)."""
    depth = 0
    for i in range(at - 1, max(-1, at - 2000), -1):
        depth += text[i] in ")]}"
        depth -= text[i] in "([{"
        if depth < 0:
            if text[i] != "{":
                return None
            close, d = None, 0
            for j in range(i, min(len(text), i + 4000)):
                d += text[j] in "([{"
                d -= text[j] in ")]}"
                if d == 0:
                    close = j
                    break
            return None if close is None else (text[i + 1:close], i)
    return None
