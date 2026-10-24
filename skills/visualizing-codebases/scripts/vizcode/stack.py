"""Framework knowledge as data: built-in packs plus the agent-written stack.yaml."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .adapters.langs import ALL, SPECS

LANGS = ("python", "scala", *dict.fromkeys(spec.lang for spec in ALL))
KINDS = ("sql-db", "doc-db", "cache", "http-in", "http-out", "http", "ws", "event", "grpc", "cloud-sdk", "spark", "mail")
GROUPS = ("imports", "routes", "effects", "ignore", "tables", "queues", "jobs")
READERS = ("literal", "segments")
HEADER = ("# stack.yaml: written by the visualizing-codebases agent from this repo's code; read by extract.py.\n"
          "# Libraries and route styles the scanner does not know built in. Commit it; edit it by hand if a fact is wrong.\n")
PACKS = Path(__file__).parent / "packs"
CODE_RULES = {"python": ("fastapi",), "scala": ("tapir", "tapir-client")}   # route framework names kept in code
FORMS = ("regex", "annotated")
FROM_ARG = "from-method-arg"
TOKENS = ("class-stem", "method-name")   # class name without a trailing `Controller`; the method's name
PATH_ARGS = ("value", "path", 0)


class StackError(ValueError):
    """Invalid pack or stack.yaml content; the message names file, language, group, entry and reason."""


@dataclass(frozen=True)
class RoutePattern:
    lang: str
    name: str
    regex: re.Pattern
    path: str
    when: str | None
    method: str | None
    source: str
    mount: bool = False   # a nested prefix (`mount: true`): listed in summary.md, never a route
    # `expand`: action -> ((METHOD, path suffix), ...); a match gives one route per pair of each action its
    # `only` / `except` groups keep (Rails `resources :users, only: [:index]`); a `param` group renames `:id`
    expand: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = ()
    # `handler_class` / `handler_method`: templates naming the handler by convention (`{path|camel}Controller`,
    # `{action}`) from the regex groups and the expanded action; structure resolves them to a method when that
    # class and method exist, else the route keeps its span-rule handler, as it does when a `nohandler` group matched
    handler_class: str | None = None
    handler_method: str | None = None


@dataclass(frozen=True)
class AnnotatedPattern:
    """A route built from a class prefix annotation and a method verb annotation (`form: annotated`)."""
    lang: str
    name: str
    when: str | None
    source: str
    prefix: tuple[str, ...]              # class annotation names whose path is the prefix
    verbs: dict[str, str]                # annotation name -> HTTP method, or "from-method-arg"
    path_args: tuple[str | int, ...]     # named args to read, then positional indexes; first present wins
    method_arg: str | None               # named arg holding the method for "from-method-arg" (None: "method")
    token: dict[str, str]                # path token -> TOKENS replacement ("[controller]": "class-stem")
    method_path: tuple[str, ...]         # method annotations whose path is appended (JAX-RS `@Path` on a method)
    absolute: tuple[str, ...] = ()       # a method path starting with one of these drops the class prefix (ASP.NET `~/`)
    skip_class: tuple[str, ...] = ()     # class annotations marking an HTTP client (Feign): such a class gives no routes


@dataclass(frozen=True)
class TablePattern:
    lang: str
    name: str
    regex: re.Pattern
    when: str | None
    source: str


@dataclass(frozen=True)
class QueuePattern:
    lang: str
    name: str
    regex: re.Pattern
    when: str | None
    delivery: str          # queue | fan-out
    source: str


@dataclass(frozen=True)
class JobPattern:
    lang: str
    name: str
    regex: re.Pattern
    when: str | None
    side: str              # define (the code a job runs) | enqueue (a call that queues one) | schedule (a timed run)
                           # | publish (a message sent to a broker topic or queue) | consume (code that receives them)
    source: str


JOB_SIDES = ("define", "enqueue", "schedule", "publish", "consume")
MESSAGE_SIDES = ("publish", "consume")   # a broker's topics and queues: named whole (`orders.created`), never split
# a file-level name bound to one string literal, for a topic written as a constant (`TOPIC = "orders"`)
_NAMED_LITERAL = re.compile(r"""^[ \t]*(?:export[ \t]+)?(?:(?:const|let|var|val|final|static|private|public|protected|readonly|"""
                            r"""internal)[ \t]+)*(?:[\w<>\[\],?]+[ \t]+)?([A-Za-z_$][\w$]*)[ \t]*(?::[ \t]*[\w<>\[\]|]+[ \t]*)?:?=[ \t]*"""
                            r"""(?:[^\n]*?(?:\?\?|\|\||\bor\b|,)[ \t]*)?["'`]([^"'`\n]+)["'`][ \t]*\)?[ \t]*;?[ \t]*$""", re.M)
# (also a setting's literal default: `env("TOPIC") ?? "orders"`, `os.getenv("TOPIC", "orders")`, `x || "orders"`)
FIELD_WORDS = re.compile(r"\b(?:private|public|protected|internal|static|readonly)\b")
CONSTANT_NAME = re.compile(r"[A-Z][A-Z0-9_]*$")   # `ROUTING_KEY = 'orders'` in a class, Kotlin `const val TOPIC`


CLASS_HEAD = re.compile(r"^\s*(?:(?:@[\w.]+(?:\([^)]*\))?|public|private|protected|internal|abstract|final|sealed|"
                        r"data|open|inner|static|export|default|case|pub(?:\([\w ]+\))?|partial|annotation|"
                        r"implicit|value|unsafe|readonly|ref|file|new|declare|const|fileprivate|indirect|expect|"
                        r"actual|inline|external|strictfp|transparent|override)\s+)*(?:class|object|interface|enum|struct|record|trait|impl|namespace|"
                        r"module|companion)\s+[\w$]")
FUNCTION_HEAD = re.compile(r"^\s*(?:(?:async\s+)?def\s|(?:fun(?!\s+interface\b)|func|function)\b|(?![^(]*\b(?:class|object|interface|enum|"
                           r"companion|struct|record|namespace|trait)\s+[\w$])(?!(?:if|elif|else|for|while|switch|with|"
                           r"try|except|case)\b)(?!(?:catch|when|match)\s)(?:[\w<>\[\],?.]+\s+)*[\w$]+\s*\([^)]*\)\s*"
                           r"(?:->\s*[^:{]+|:\s*[\w<>\[\]?, .]+)?\s*[:{]\s*$)")


def in_function(lines: list[str], i: int) -> bool:
    """Line i (0-based) sits inside a function: walking out through the lines above it with less indent, a
    function's head (`def a(p):`, `void a() {`, `fun a() {`) comes before a class's or an object's or the file's top;
    a block between (`if (x) {`, `with lock:`, `try:`) is passed through."""
    indent = len(lines[i]) - len(lines[i].lstrip())
    for j in range(i - 1, -1, -1):
        line = lines[j]
        if line.strip() and (lead := len(line) - len(line.lstrip())) < indent:
            if FUNCTION_HEAD.match(line):
                return True
            if lead == 0 or CLASS_HEAD.match(line):
                return False
            indent = lead
    return False


def file_literals(src: str) -> dict[str, str]:
    """A file's names bound once to a string literal at its top, as a declared field (`private static final String
    TOPIC = "x"`) or as a constant-cased name (`ROUTING_KEY = 'orders'` in a class): a name bound to two different
    ones, or a function's local (`final String topic = "x"` in a method), is left out."""
    seen: dict[str, set[str]] = {}
    lines = src.split("\n")
    for m in _NAMED_LITERAL.finditer(src):
        i = src.count("\n", 0, m.start())
        line = lines[i]
        if not line[:1].isspace() or ((CONSTANT_NAME.match(m.group(1)) or FIELD_WORDS.search(line.split("=", 1)[0]))
                                      and not in_function(lines, i)):
            seen.setdefault(m.group(1), set()).add(m.group(2))
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def _local_literal(src: str, name: str, start: int, end: int) -> str | None:
    """The literal a name was last bound to in lines start..end-1 of src (1-based), the function around a call."""
    lines = src.split("\n")[max(start - 1, 0):max(end - 1, 0)]
    if lines:   # the function's own line from its body on (`fun a() { val t = "x"; ..`): its parameters are none
        lines[0] = lines[0].split("{", 1)[1] if "{" in lines[0] else ""
    # a statement binding the name (`topic = 'x'`, `val topic = "x"`; `;`-separated ones too), never a keyword argument
    # or a parameter default (`topic='x')`, `topic='x',`)
    pat = re.compile(rf"(?:^|;)\s*(?:(?:const|let|var|val|final|[\w<>\[\]?]+)\s+)*{re.escape(name)}\s*"
                     rf"(?::\s*[\w<>\[\]|?]+\s*)?:?=(?!=)\s*[\"'`]([^\"'`\n]+)[\"'`]\s*(?=;|$)")
    return next((m.group(1) for line in reversed(lines) if (m := pat.search(line))), None)


@dataclass(frozen=True)
class Effect:
    name: str
    match: str


@dataclass
class Stack:
    imports: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    ignore: dict[str, list[str]] = field(default_factory=dict)
    stack_ignore: dict[str, list[str]] = field(default_factory=dict)   # the stack.yaml entries of `ignore`
    # folder -> a path prefix only config sets (a servlet context path, a URI version), for the routes under it
    base_paths: dict[str, str] = field(default_factory=dict)
    effects: dict[str, list[Effect]] = field(default_factory=dict)
    patterns: list[RoutePattern | AnnotatedPattern] = field(default_factory=list)
    tables: list[TablePattern] = field(default_factory=list)
    queues: list[QueuePattern] = field(default_factory=list)
    jobs: list[JobPattern] = field(default_factory=list)
    digest: str | None = None
    overrides: list[dict] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)   # stack.yaml `exclude`: globs every scan leaves out


def _fail(fname: str, where: str, name: str | None, reason: str) -> StackError:
    return StackError(f"{fname}: {where}" + (f" ({name})" if name else "") + f": {reason}")


def _trim(prefix, lang: str):
    """A prefix written with its language's separator at the end (`java.`, `std::`) names the same library
    without it; `node:` keeps its single `:` (see prefix_match)."""
    s = sep(lang)
    if isinstance(prefix, str) and len(prefix) > len(s) and prefix.endswith(s):
        return prefix[:-len(s)]
    return prefix


def _add_imports(st: Stack, fname: str, lang: str, entries: list, source: str) -> None:
    have = st.imports.setdefault(lang, [])
    for i, e in enumerate(entries):
        where = f"{lang}.imports[{i}]"
        if not isinstance(e, dict):
            raise _fail(fname, where, None, "must be a mapping with prefix and kind")
        name = _trim(e.get("prefix"), lang) if isinstance(e.get("prefix"), str) else None
        if extra := sorted(set(e) - {"prefix", "kind"}):
            raise _fail(fname, where, name, f"unknown key '{extra[0]}'")
        if not name:
            raise _fail(fname, where, None, "missing prefix")
        if "kind" not in e:
            raise _fail(fname, where, name, "missing kind")
        if e["kind"] not in KINDS:
            raise _fail(fname, where, name, f"unknown kind '{e['kind']}' (one of {', '.join(KINDS)})")
        kind = e["kind"]
        old = next((h for h in have if h[0] == name), None)
        if old is None:
            have.append((name, kind, source))
        elif old[1] != kind:
            have[have.index(old)] = (name, kind, source)
            st.overrides.append({"lang": lang, "prefix": name, "pack_kind": old[1], "kind": kind})


def _add_ignore(st: Stack, fname: str, lang: str, entries: list, source: str) -> None:
    have = st.ignore.setdefault(lang, [])
    mine = st.stack_ignore.setdefault(lang, []) if source == "stack.yaml" else []
    for i, e in enumerate(entries):
        if not isinstance(e, str) or not e:
            raise _fail(fname, f"{lang}.ignore[{i}]", None, "must be a prefix string")
        e = _trim(e, lang)
        if e not in have:
            have.append(e)
        if e not in mine and source == "stack.yaml":
            mine.append(e)


def _add_effects(st: Stack, fname: str, lang: str, entries: list) -> None:
    have = st.effects.setdefault(lang, [])
    for i, e in enumerate(entries):
        where = f"{lang}.effects[{i}]"
        if isinstance(e, str):
            e = {"name": e}
        if not isinstance(e, dict) or not isinstance(e.get("name"), str) or not e["name"]:
            raise _fail(fname, where, None, "must be a type name or {name, match}")
        name, match = e["name"], e.get("match", "both")
        if extra := sorted(set(e) - {"name", "match"}):
            raise _fail(fname, where, name, f"unknown key '{extra[0]}'")
        if match not in ("type", "both"):
            raise _fail(fname, where, name, f"unknown match '{match}' (type or both)")
        if all(x.name != name for x in have):
            have.append(Effect(name, match))


def _place(st: Stack, have: list, group: str, fname: str, where: str, name: str, new) -> None:
    """Add a route or table entry. A stack.yaml entry named like a pack entry of its language and group
    replaces it in place (listed in `overrides`); any other repeated name is an error."""
    old = next((i for i, p in enumerate(have) if p.lang == new.lang and p.name == name), None)
    if old is None:
        have.append(new)
    elif new.source == "stack.yaml" and have[old].source == "pack":
        have[old] = new
        st.overrides.append({"lang": new.lang, "group": group, "name": name})
    else:
        raise _fail(fname, where, name, f"duplicate {group[:-1]} name")


def _names(fname: str, where: str, name: str, e: dict, key: str) -> tuple[str, ...]:
    v = e.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
        raise _fail(fname, where, name, f"{key} must be a list of annotation names")
    return tuple(v)


def _path_arg(x) -> bool:
    """An argument name, or a position (a non-negative int, not a bool)."""
    return (isinstance(x, str) and bool(x)) or (isinstance(x, int) and not isinstance(x, bool) and x >= 0)


def _annotated(fname: str, lang: str, where: str, name: str, e: dict, source: str) -> AnnotatedPattern:
    if extra := sorted(set(e) - {"name", "form", "when", "prefix", "verbs", "path_args", "method_arg", "token",
                                 "method_path", "absolute", "skip_class"}):
        raise _fail(fname, where, name, f"unknown key '{extra[0]}'")
    if "verbs" not in e:
        raise _fail(fname, where, name, "missing verbs")
    verbs = e["verbs"]
    if not isinstance(verbs, dict) or not verbs or not all(isinstance(k, str) and k for k in verbs):
        raise _fail(fname, where, name, "verbs must be a non-empty mapping of annotation name to HTTP method")
    for k, v in verbs.items():
        if not (isinstance(v, str) and (v == FROM_ARG or re.fullmatch(r"\w+", v))):
            raise _fail(fname, where, name, f"verb {k}: {v!r} is not an HTTP method word or {FROM_ARG}")
    path_args = e.get("path_args", list(PATH_ARGS))
    if not isinstance(path_args, list) or not path_args or not all(map(_path_arg, path_args)):
        raise _fail(fname, where, name, "path_args must be a non-empty list of argument names or positions")
    method_arg = e.get("method_arg", "method")
    if not isinstance(method_arg, str) or not method_arg:
        raise _fail(fname, where, name, "method_arg must be an argument name")
    token = e.get("token", {})
    if not isinstance(token, dict) or not all(isinstance(k, str) and k for k in token):
        raise _fail(fname, where, name, "token must be a mapping of path token to replacement")
    for k, v in token.items():
        if v not in TOKENS:
            raise _fail(fname, where, name, f"token '{k}': unknown replacement '{v}' (one of {', '.join(TOKENS)})")
    if e.get("when") is not None and not isinstance(e["when"], str):
        raise _fail(fname, where, name, "when must be an import prefix")
    prefix, method_path = _names(fname, where, name, e, "prefix"), _names(fname, where, name, e, "method_path")
    skip_class = _names(fname, where, name, e, "skip_class")
    absolute = e.get("absolute", [])
    if not isinstance(absolute, list) or not all(isinstance(x, str) and x for x in absolute):
        raise _fail(fname, where, name, "absolute must be a list of path starts")
    if lang not in SPECS:
        raise _fail(fname, where, name, f"the annotated form needs a language the generic walker parses (not {lang})")
    return AnnotatedPattern(
        lang, name, _trim(e.get("when"), lang), source, prefix,
        {k: v if v == FROM_ARG else v.upper() for k, v in verbs.items()}, tuple(path_args), method_arg,
        dict(token), method_path, tuple(absolute), skip_class)


def _add_routes(st: Stack, fname: str, lang: str, entries: list, source: str) -> None:
    for i, e in enumerate(entries):
        where = f"{lang}.routes[{i}]"
        name = e.get("name") if isinstance(e, dict) and isinstance(e.get("name"), str) else None
        if not isinstance(e, dict):
            raise _fail(fname, where, None, "must be a mapping")
        form = e.get("form", "regex")
        if form not in FORMS:
            raise _fail(fname, where, name, f"unknown form '{form}' (regex or annotated)")
        if form == "annotated":
            if not name:
                raise _fail(fname, where, None, "missing name")
            if name in CODE_RULES.get(lang, ()):
                raise _fail(fname, where, name, "clashes with a built-in rule")
            _place(st, st.patterns, "routes", fname, where, name, _annotated(fname, lang, where, name, e, source))
            continue
        if extra := sorted(set(e) - {"name", "form", "regex", "path", "when", "method", "mount", "expand",
                                     "handler_class", "handler_method"}):
            raise _fail(fname, where, name, f"unknown key '{extra[0]}'")
        for key in ("name", "regex"):
            if not isinstance(e.get(key), str) or not e[key]:
                raise _fail(fname, where, name, f"missing {key}")
        reader = e.get("path", "literal")   # the path reader: `literal` when omitted
        if reader not in READERS:
            raise _fail(fname, where, name, f"unknown path reader '{reader}' (one of {', '.join(READERS)})")
        if name in CODE_RULES.get(lang, ()):
            raise _fail(fname, where, name, "clashes with a built-in rule")
        if e.get("when") is not None and not isinstance(e["when"], str):
            raise _fail(fname, where, name, "when must be an import prefix")
        if e.get("mount") is not None and not isinstance(e["mount"], bool):
            raise _fail(fname, where, name, "mount must be true or false")
        mount = e.get("mount") is True
        if e.get("method") is not None and not (isinstance(e["method"], str) and re.fullmatch(r"\w+", e["method"])):
            raise _fail(fname, where, name, "method must be a word such as GET or ANY")
        try:
            regex = re.compile(e["regex"], re.M)
        except re.error as err:
            raise _fail(fname, where, name, f"regex does not compile: {err}") from None
        if "path" not in regex.groupindex:
            raise _fail(fname, where, name, "regex has no path group")
        expand = _expand(fname, where, name, e.get("expand"))
        if mount and expand:
            raise _fail(fname, where, name, "a mount has no expand")
        if mount:
            if extra := sorted(set(regex.groupindex) - {"path", "target", "module"}):
                raise _fail(fname, where, name, f"mount regex has group '{extra[0]}': only path and target")
        elif "method" not in regex.groupindex and not e.get("method") and not expand:
            raise _fail(fname, where, name, "no method source: add a method group, or method: "
                        "(also required with a methods group, for a match where that group is empty)")
        method = e["method"].upper() if e.get("method") else None
        h_class, h_method = _handler_templates(fname, where, name, e, regex, expand, mount)
        _place(st, st.patterns, "routes", fname, where, name,
               RoutePattern(lang, name, regex, reader, _trim(e.get("when"), lang), method, source, mount, expand,
                            h_class, h_method))


TEMPLATE_FIELD = re.compile(r"\{(\w+(?:,\w+)*)(?:\|(\w+))?\}")   # `{a,b|camel}`: the first of a, b with a value
TEMPLATE_FILTERS = {"camel": lambda v: "/".join("".join(w[:1].upper() + w[1:] for w in re.split(r"[_-]", part))
                                                for part in v.split("/"))}


def _handler_templates(fname: str, where: str, name: str, e: dict, regex: re.Pattern, expand: tuple,
                       mount: bool) -> tuple[str | None, str | None]:
    """`handler_class` and `handler_method`, both or neither: templates whose `{group}` / `{group|camel}` fields
    (or `{a,b}`: the first with a value) name regex groups, or `action` (the expanded action) on an entry with
    `expand`."""
    values = [e.get("handler_class"), e.get("handler_method")]
    if values == [None, None]:
        return None, None
    if mount:
        raise _fail(fname, where, name, "a mount has no handler_class or handler_method")
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise _fail(fname, where, name, "handler_class and handler_method go together, each a template string")
    known = set(regex.groupindex) | ({"action"} if expand else set())
    for v in values:
        for fields, filt in TEMPLATE_FIELD.findall(v):
            for field in fields.split(","):
                if field not in known:
                    raise _fail(fname, where, name, f"template field '{field}' is not a regex group"
                                + (" or action" if expand else ""))
            if filt and filt not in TEMPLATE_FILTERS:
                raise _fail(fname, where, name, f"unknown template filter '{filt}' (one of {', '.join(TEMPLATE_FILTERS)})")
    return values[0].strip(), values[1].strip()


def _fill(template: str, values: dict) -> str | None:
    """The template with its fields filled in; None when a field's value is empty."""
    missing = False

    def one(m: re.Match) -> str:
        nonlocal missing
        v = next((x for k in m.group(1).split(",") if (x := (values.get(k) or "").strip())), "")
        missing = missing or not v
        return TEMPLATE_FILTERS[m.group(2)](v) if m.group(2) else v
    out = TEMPLATE_FIELD.sub(one, template)
    return None if missing else out


def _named_handler(pat: RoutePattern, m: re.Match, action: str | None = None) -> dict:
    """The route's `handler_class` and `handler_method`, when the pattern names them, every field has a value and
    the match has no `nohandler` text (an option naming another handler, such as Rails `controller:`)."""
    if not pat.handler_class or (m.groupdict().get("nohandler") or "").strip():
        return {}
    values = {**m.groupdict(), **({"action": action} if action else {})}
    cls, meth = _fill(pat.handler_class, values), _fill(pat.handler_method, values)
    return {"handler_class": cls, "handler_method": meth} if cls and meth else {}


EXPAND_ITEM = re.compile(r"(\w+)(?:\s+(/\S*))?")


def _expand(fname: str, where: str, name: str | None, value) -> tuple:
    """`expand: {index: GET, show: GET /:id, update: [PATCH /:id, PUT /:id]}` -> the RoutePattern tuple."""
    if value is None:
        return ()
    shape = "expand must map an action to `METHOD` or `METHOD /suffix`, or a list of them"
    if not isinstance(value, dict) or not value:
        raise _fail(fname, where, name, shape)
    out = []
    for action, items in value.items():
        items = items if isinstance(items, list) else [items]
        pairs = []
        for item in items:
            if not isinstance(item, str) or not (m := EXPAND_ITEM.fullmatch(item.strip())):
                raise _fail(fname, where, name, shape)
            pairs.append((m.group(1).upper(), m.group(2) or ""))
        if not isinstance(action, str) or not pairs:
            raise _fail(fname, where, name, shape)
        out.append((action, tuple(pairs)))
    return tuple(out)


ACTION_WORD = re.compile(r"(?<!%)\b\w+")   # `[:index, :show]`, `%i[index show]`, `:index`, `"index"`


def _add_tables(st: Stack, fname: str, lang: str, entries: list, source: str) -> None:
    for i, e in enumerate(entries):
        where = f"{lang}.tables[{i}]"
        name = e.get("name") if isinstance(e, dict) and isinstance(e.get("name"), str) else None
        if not isinstance(e, dict):
            raise _fail(fname, where, None, "must be a mapping")
        if extra := sorted(set(e) - {"name", "regex", "when"}):
            raise _fail(fname, where, name, f"unknown key '{extra[0]}'")
        for key in ("name", "regex"):
            if not isinstance(e.get(key), str) or not e[key]:
                raise _fail(fname, where, name, f"missing {key}")
        if e.get("when") is not None and not isinstance(e["when"], str):
            raise _fail(fname, where, name, "when must be an import prefix")
        try:
            regex = re.compile(e["regex"], re.M)
        except re.error as err:
            raise _fail(fname, where, name, f"regex does not compile: {err}") from None
        if "table" not in regex.groupindex:
            raise _fail(fname, where, name, "regex has no table group")
        _place(st, st.tables, "tables", fname, where, name,
               TablePattern(lang, name, regex, _trim(e.get("when"), lang), source))


def _add_queues(st: Stack, fname: str, lang: str, entries: list, source: str) -> None:
    for i, e in enumerate(entries):
        where = f"{lang}.queues[{i}]"
        name = e.get("name") if isinstance(e, dict) and isinstance(e.get("name"), str) else None
        if not isinstance(e, dict):
            raise _fail(fname, where, None, "must be a mapping")
        if extra := sorted(set(e) - {"name", "regex", "when", "delivery"}):
            raise _fail(fname, where, name, f"unknown key '{extra[0]}'")
        for key in ("name", "regex"):
            if not isinstance(e.get(key), str) or not e[key]:
                raise _fail(fname, where, name, f"missing {key}")
        if e.get("delivery") not in ("queue", "fan-out"):
            raise _fail(fname, where, name, "delivery must be queue or fan-out")
        if e.get("when") is not None and not isinstance(e["when"], str):
            raise _fail(fname, where, name, "when must be an import prefix")
        try:
            regex = re.compile(e["regex"], re.M)
        except re.error as err:
            raise _fail(fname, where, name, f"regex does not compile: {err}") from None
        _place(st, st.queues, "queues", fname, where, name,
               QueuePattern(lang, name, regex, _trim(e.get("when"), lang), e["delivery"], source))


def _add_jobs(st: Stack, fname: str, lang: str, entries: list, source: str) -> None:
    for i, e in enumerate(entries):
        where = f"{lang}.jobs[{i}]"
        name = e.get("name") if isinstance(e, dict) and isinstance(e.get("name"), str) else None
        if not isinstance(e, dict):
            raise _fail(fname, where, None, "must be a mapping")
        if extra := sorted(set(e) - {"name", "regex", "when", "side"}):
            raise _fail(fname, where, name, f"unknown key '{extra[0]}'")
        for key in ("name", "regex"):
            if not isinstance(e.get(key), str) or not e[key]:
                raise _fail(fname, where, name, f"missing {key}")
        if e.get("side") not in JOB_SIDES:
            raise _fail(fname, where, name, f"side must be one of {', '.join(JOB_SIDES)}")
        if e.get("when") is not None and not isinstance(e["when"], str):
            raise _fail(fname, where, name, "when must be an import prefix")
        try:
            regex = re.compile(e["regex"], re.M)
        except re.error as err:
            raise _fail(fname, where, name, f"regex does not compile: {err}") from None
        if e["side"] in ("enqueue", *MESSAGE_SIDES) and "job" not in regex.groupindex:
            raise _fail(fname, where, name, f"a {e['side']} regex needs a `job` group naming the "
                        + ("job" if e["side"] == "enqueue" else "topic or queue"))
        _place(st, st.jobs, "jobs", fname, where, name,
               JobPattern(lang, name, regex, _trim(e.get("when"), lang), e["side"], source))


def _read(st: Stack, fname: str, doc, source: str) -> None:
    if doc is None:
        return
    if not isinstance(doc, dict):
        raise _fail(fname, "top level", None, "must be a mapping of language to groups")
    for lang, groups in doc.items():
        if lang == "exclude":
            if not isinstance(groups, list) or not all(isinstance(g, str) and g for g in groups):
                raise _fail(fname, "exclude", None, "must be a list of globs")
            st.excludes += [g for g in groups if g not in st.excludes]
            continue
        if lang == "base_paths":
            if not isinstance(groups, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                                       for k, v in groups.items()):
                raise _fail(fname, "base_paths", None, "must be a mapping of folder to path")
            if bad := [k for k, v in groups.items() if not v.startswith("/")]:
                raise _fail(fname, "base_paths", bad[0], "a path must start with /")
            st.base_paths.update({k.strip("/") or ".": v for k, v in groups.items()})
            continue
        if lang not in LANGS:
            raise _fail(fname, f"unknown language '{lang}'", None, f"the scanner parses {', '.join(LANGS)}")
        if groups is None:
            continue
        if not isinstance(groups, dict):
            raise _fail(fname, lang, None, "must be a mapping of groups")
        for group, entries in groups.items():
            if group not in GROUPS:
                raise _fail(fname, f"{lang}: unknown group '{group}'", None, f"one of {', '.join(GROUPS)}")
            if entries is None:
                continue
            if not isinstance(entries, list):
                raise _fail(fname, f"{lang}.{group}", None, "must be a list")
            if group == "imports":
                _add_imports(st, fname, lang, entries, source)
            elif group == "ignore":
                _add_ignore(st, fname, lang, entries, source)
            elif group == "effects":
                if lang != "scala":
                    raise _fail(fname, f"{lang}.effects", None, "effects are Scala only for now")
                _add_effects(st, fname, lang, entries)
            elif group == "tables":
                _add_tables(st, fname, lang, entries, source)
            elif group == "queues":
                _add_queues(st, fname, lang, entries, source)
            elif group == "jobs":
                _add_jobs(st, fname, lang, entries, source)
            else:
                _add_routes(st, fname, lang, entries, source)


def _where(err: Exception, path) -> str:
    """A YAML error's text naming the file it is in, not `"<unicode string>"`."""
    return str(err).replace('"<unicode string>"', f'"{path}"')


def load(stack_file: Path | None) -> Stack:
    """Packs always, then stack_file when it exists. Raises StackError."""
    st = Stack()
    for lang in LANGS:
        pack = PACKS / f"{lang}.yaml"
        _read(st, pack.name, yaml.safe_load(pack.read_text(encoding="utf-8")), "pack")
    if stack_file is not None and Path(stack_file).is_file():
        raw = Path(stack_file).read_bytes()
        try:
            text = raw.removeprefix(b"\xef\xbb\xbf").decode().replace("\r\n", "\n")
        except UnicodeDecodeError as err:
            raise StackError(f"{Path(stack_file).name}: not valid UTF-8: {err}") from None
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError as err:
            raise StackError(f"{stack_file}: not valid YAML: {_where(err, stack_file)}") from None
        # of the parsed content: a comment, whitespace or line-ending edit digests the same
        st.digest = hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                              default=str).encode()).hexdigest()
        _read(st, Path(stack_file).name, doc, "stack.yaml")
    return st


_DEFAULT: list[Stack] = []


def default() -> Stack:
    """The packs alone, loaded once: for callers that parse a file without a repository."""
    if not _DEFAULT:
        _DEFAULT.append(load(None))
    return _DEFAULT[0]


def ensure_header(stack_file: Path) -> None:
    """Prepend HEADER when the first line is not its first line; the rest stays byte for byte."""
    raw = Path(stack_file).read_bytes()
    bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
    body = raw[len(bom):]
    if body.split(b"\n", 1)[0].rstrip(b"\r") != HEADER.split("\n", 1)[0].encode():
        crlf = body.split(b"\n", 1)[0].endswith(b"\r")
        header = (HEADER.replace("\n", "\r\n") if crlf else HEADER).encode()
        Path(stack_file).write_bytes(bom + header + body)


def add_excludes(stack_file: Path, globs: list[str]) -> list[str]:
    """Add the globs stack.yaml's `exclude` list lacks (creating the file with HEADER when there is none), so a
    rescan without `--exclude` leaves the same files out. The list is rewritten at the end of the file, one quoted
    glob per line; the rest stays as written. Returns the globs added."""
    path = Path(stack_file)
    text = path.read_text(encoding="utf-8") if path.is_file() else HEADER
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as err:
        raise StackError(f"{path}: not valid YAML: {_where(err, path)}") from None
    have = doc.get("exclude") if isinstance(doc, dict) and isinstance(doc.get("exclude"), list) else []
    added = [g for g in dict.fromkeys(globs) if g not in have]
    if not added:
        return []
    kept, inside = [], False
    for line in text.splitlines(keepends=True):
        if re.match(r"exclude\s*:", line):
            inside = True
        elif inside and (not line.strip() or line[0] in " \t-"):
            continue
        else:
            inside = False
            kept.append(line)
    body = "".join(kept)
    body += "" if not body or body.endswith("\n") else "\n"
    quoted = ["'" + g.replace("'", "''") + "'" for g in [*have, *added]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + "exclude:\n" + "".join(f"  - {q}\n" for q in quoted), encoding="utf-8")
    return added


def sep(lang: str) -> str:
    """The separator of the language's import paths: `.` for Python and Scala, else its table's."""
    return SPECS[lang].sep if lang in SPECS else "."


def prefix_match(prefix: str, target: str, separator: str = ".") -> bool:
    """On segment boundaries; a prefix ending in a single `:` (a scheme such as `node:`) covers whatever
    follows it, but not one ending in `::` (Rust `std::`), which stays segment-bounded."""
    scheme = prefix.endswith(":") and not prefix.endswith("::")
    return target == prefix or target.startswith(prefix if scheme else prefix + separator)


def sink_kinds(st: Stack, lang: str, target: str) -> list[dict]:
    """The kind of the longest imports prefix naming the target (`jakarta.ws.rs.client` over `jakarta.ws.rs`)."""
    hits = [(p, kind) for p, kind, _ in st.imports.get(lang, []) if prefix_match(p, target, sep(lang))]
    longest = max((len(p) for p, _ in hits), default=0)
    return [{"kind": kind, "lib": p} for p, kind in hits if len(p) == longest]


def targets(imp: dict, lang: str = "python") -> list[str]:
    """What an import names: `X.Y` for each name of `from X import Y` (absolute), else the target alone;
    a language whose names are exports (`names_extend`) names the target alone. A leading separator (Rust
    `::serde`) is dropped."""
    s = sep(lang)
    t = imp["target"].lstrip(".") if s == "." else imp["target"].removeprefix(s)
    if imp.get("names") and not imp["relative"] and (lang not in SPECS or SPECS[lang].names_extend):
        return [f"{t}{s}{n}" for n in imp["names"]]
    return [t]


def import_sinks(st: Stack, lang: str, imp: dict) -> list[dict]:
    """Sink kinds of every name an import brings in, once per library."""
    out = []
    for t in targets(imp, lang):
        out += [h for h in sink_kinds(st, lang, t) if h not in out]
    return out


def covered(st: Stack, lang: str, target: str) -> bool:
    """An import that some imports, ignore or route `when` prefix of the language names."""
    prefixes = [p for p, _, _ in st.imports.get(lang, [])] + st.ignore.get(lang, []) \
        + [p.when for p in (*st.patterns, *st.tables) if p.lang == lang and p.when]
    return any(prefix_match(p, target, sep(lang)) for p in prefixes)


def effect_names(st: Stack, lang: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(names matched as declared types, names also matched in values)."""
    es = st.effects.get(lang, [])
    return tuple(e.name for e in es), tuple(e.name for e in es if e.match == "both")


HTTP_VERBS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS", "TRACE", "CONNECT")
VERB_CONSTANT = re.compile(r"[A-Za-z_]\w*(?:(?:\.|::|\\|->)[A-Za-z_]\w*)+")


def verb_of(text: str) -> str | None:
    """The HTTP method a qualified constant names by its last part, case-insensitively, with a `Method` or `Http`
    prefix dropped (`http.MethodHead` -> HEAD, `HttpMethod.GET` -> GET, `Method::POST` -> POST); else None."""
    last = re.split(r"\.|::|\\|->", text.strip())[-1].upper()
    for word in (last, re.sub(r"^(?:METHOD|HTTP)_?", "", last)):
        if word in HTTP_VERBS:
            return word
    return None


def _methods(text: str) -> list[str]:
    """The methods a `methods` group lists: quoted words, and qualified constants naming a verb."""
    return [m.group(1).upper() if m.group(1) else verb_of(m.group(0))
            for m in re.finditer(rf"[\"'](\w+)[\"']|{VERB_CONSTANT.pattern}", text)
            if m.group(1) or verb_of(m.group(0))]


# a parameter's name inside `{}` with what frameworks write around it: a catch-all `*`/`**`, an optional `?`, a Go
# wildcard `...`, a constraint after `:` (`{id:int}`, `{id:[0-9]+}`, `{id:minlength(1)}`)
BRACED_PARAM = re.compile(r"\{\*{0,2}(\w+)(?:\?|\.\.\.|:(?:[^{}]|\{[^{}]*\})*)?\}")
# `:id`, optionally `:id?` or `:id(\d+)` (a regex in parentheses)
COLON_PARAM = re.compile(r"(?:(?<=/)|^):(\w+)(?:\?|\((?:[^()]|\([^()]*\))*\))?")


def normalise(path: str) -> str:
    """A route path in the key form: `/` first, no trailing `/`, each parameter as `{name}` (`<int:id>`, `:id`,
    `{id:int}`, `{id?}`, `{*rest}` -> `{id}`, `{rest}`)."""
    path = re.sub(r"<(?:[^<>:]*:)?([^<>]+)>", r"{\1}", path.strip())
    path = COLON_PARAM.sub(r"{\1}", path)
    path = BRACED_PARAM.sub(r"{\1}", path)
    return "/" + path.strip("/")


SEGMENT = re.compile(r'"([^"]*)"|\w+\(\s*(?:"([^"]*)"|(\w+))\s*\)|(\w+)')


def read_path(text: str, reader: str) -> str:
    if reader == "literal":
        return normalise(text)
    segs = []
    for lit, qcap, wcap, bare in SEGMENT.findall(text):
        if cap := qcap or wcap:
            segs.append("{" + cap + "}")
        elif bare and bare != "Root":
            segs.append("{" + bare + "}")
        elif lit:
            segs += [s for s in lit.split("/") if s]
    return normalise("/".join(segs))


def _handler(spans: list[tuple[int, int, str]], line: int, file_id: str, below: bool = True) -> str:
    """The innermost method around the line, else (below) the first one below it, else the file."""
    inside = [s for s in spans if s[0] <= line <= s[1]]
    if inside:
        return max(inside, key=lambda s: s[0])[2]
    if not below:
        return file_id
    after = [s for s in spans if s[0] > line]
    return min(after, key=lambda s: s[0])[2] if after else file_id


def import_names(imports: list[dict], lang: str = "python") -> list[str]:
    """Every absolute target the imports name (see targets): what a `when` prefix is matched against."""
    return [t for i in imports if not i["relative"] for t in targets(i, lang)]


def _when_line(when: str, imports: list[dict], lang: str) -> int | None:
    return next((i["line"] for i in imports if not i["relative"]
                 and any(prefix_match(when, t, sep(lang)) for t in targets(i, lang))), None)


def _matches(st: Stack, lang: str, src: str, imports: list[str], mount: bool):
    """(pattern, match, text) of every path match of the language's regex patterns (mounts or routes). A route
    written with the empty string (`route("")`), or matched by a pattern whose path group is empty by design
    (`(?P<path>)`: the route takes its mount's path), is the path of the mount around it; an empty mount adds
    nothing, and a match with no path written (`route()`) is no route."""
    for pat in st.patterns:
        if not isinstance(pat, RoutePattern) or pat.lang != lang or pat.mount != mount \
                or (pat.when and not any(prefix_match(pat.when, i, sep(lang)) for i in imports)):
            continue
        for m in pat.regex.finditer(src):
            if text := (m.group("path") or "").strip():
                yield pat, m, text
            elif not mount and m.group("path") == "" and ("(?P<path>)" in pat.regex.pattern or (
                    0 < m.start("path") < len(src) and src[m.start("path") - 1] in "\"'`"
                    and src[m.end("path")] == src[m.start("path") - 1])):
                yield pat, m, ""


def _call_end_line(src: str, at: int, line: int) -> int:
    """The line a registration call that starts at `at` ends on: the line of the `)` closing the first `(` on its
    line (strings skipped), or its own line when the call has no parentheses there (`get '/x' do`)."""
    nl = src.find("\n", at)
    nl = len(src) if nl < 0 else nl
    i = src.find("(", at, nl)
    if i < 0:
        return line
    depth, quote = 0, None
    while i < len(src):
        ch = src[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            quote = None if ch == quote else quote
        elif ch in "\"'`":
            quote = ch
        else:
            depth += ch in "([{"
            depth -= ch in ")]}"
            if depth == 0:
                return line + src.count("\n", at, i)
        i += 1
    return line


def find_routes(st: Stack, lang: str, src: str, imports: list[str], spans: list[tuple[int, int, str]],
                file_id: str, mounts: list[dict] | None = None) -> list[dict]:
    """Route facts from every pattern of the language that applies to the file (imports: import_names). A match
    of a pattern with a `handler` group carries the group's text as `handler_name` for structure to resolve; such
    a pattern names its handler in the call, so when the group is empty (an inline function) the handler is the
    method around the match or the file, never the method below it (the rule for decorators). The file's `mounts`
    (find_mounts) compose onto the routes registered on them (compose)."""
    out = []
    for pat, m, text in _matches(st, lang, src, imports, False):
        groups = pat.regex.groupindex
        if pat.expand:
            only, exclude = ({w for w in ACTION_WORD.findall(m.group(g) or "")} if g in groups and m.group(g)
                             else None for g in ("only", "except"))
            line = src.count("\n", 0, m.start()) + 1
            handler = _handler(spans, line, file_id, "handler" not in groups)
            base = read_path(text, pat.path)
            param = (m.group("param") or "").strip() if "param" in groups else ""
            out += [{"method": method, "handler": handler, "line": line,
                     "path": normalise(base + (re.sub(r"(?<=/):id\b", ":" + param, suffix) if param else suffix)),
                     "framework": pat.name, "source": pat.source, "at": m.start(), **_named_handler(pat, m, action)}
                    for action, pairs in pat.expand
                    if (only is None or action in only) and (exclude is None or action not in exclude)
                    for method, suffix in pairs]
            continue
        methods = _methods(m.group("methods") or "") if "methods" in groups else []
        if not methods and "method" in groups and m.group("method"):
            methods = [verb_of(m.group("method")) or m.group("method")]
        default = {} if methods else {"method_default": True}   # the method the framework serves when none is named
        methods = [x.upper() for x in methods] or ([pat.method] if pat.method else [])
        line = src.count("\n", 0, m.start()) + 1
        handler = _handler(spans, line, file_id, "handler" not in groups)
        named = m.group("handler") if "handler" in groups else None
        on_mount = {"on_mount": True} if "(?P<path>)" in pat.regex.pattern else {}
        call_end = _call_end_line(src, m.start(), line)
        for method in methods:
            out.append({"method": method, "path": read_path(text, pat.path), "handler": handler,
                        "line": line, "framework": pat.name, "source": pat.source, "at": m.start(),
                        "call_end": call_end,
                        **({"handler_name": named.strip()} if named and named.strip() else {}),
                        **_named_handler(pat, m), **on_mount, **default})
    compose(src, out, mounts or [], lang)
    # a route on its mount's own path with no mount around it (`resource(PATHS)`): its path is unknown
    return [r for r in out if not r.pop("on_mount", None) or r.pop("composed_on", None)]


def find_mounts(st: Stack, lang: str, src: str, imports: list[str]) -> list[dict]:
    """Mount facts (nested prefixes) from the `mount: true` patterns that apply to the file. `at` and `call` (where
    the match and the call holding its path start) are for compose, which removes them."""
    out = []
    for pat, m, text in _matches(st, lang, src, imports, True):
        target = m.group("target") if "target" in pat.regex.groupindex else None
        module = (m.group("module") or "").strip() if "module" in pat.regex.groupindex else ""
        out.append({"path": read_path(text, pat.path), "target": (target or "").strip() or None,
                    "line": src.count("\n", 0, m.start()) + 1, "framework": pat.name, "source": pat.source,
                    "at": m.start(), "call": src.rfind("(", m.start(), m.start("path")),
                    **({"module": module} if module else {})})
    return out


_LINE_STRINGS = r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\''
# a JS regex literal (`/https?:\/\//`), kept like a string: a `/` after an operator or an opening bracket starts one,
# never a division
REGEX_LITERAL = r"(?<=[(,=:!&|?{};\[])\s*/(?![/*])(?:\\.|\[(?:\\.|[^\]\n\\])*\]|[^/\n\\\[])+/[a-z]*"
C_COMMENTS = re.compile(_LINE_STRINGS + r"|`[^`]*`|" + REGEX_LITERAL + r"|(//[^\n]*|/\*[\s\S]*?\*/)")
HASH_COMMENTS = re.compile(_LINE_STRINGS + r"|(#[^\n]*)")
CHAIN_STEP = re.compile(r"\s*(?:\.|::|->|\?\.)\s*[A-Za-z_]\w*\s*(?=[(\[{])")
HEAD = re.compile(r"@?\s*(\$?[A-Za-z_]\w*)\s*(?:\.|::|->)")
HEAD_BEFORE = re.compile(r"(\$?[A-Za-z_]\w*)\s*$")
BINDING = re.compile(r"(?<![\w.$])(\$?[A-Za-z_]\w*)\s*(?::\s*[\w.<>\[\], ]+?\s*)?(?::=|=(?![=>]))")
BOUND_TO = re.compile(r"\s*(?:(?:new\s+)?[\w.$:]+\s*\(\s*\{?\s*)?")


PASSED_TO = re.compile(r"([A-Za-z_][\w.]*)\(\s*$")   # the call a mount is the first argument of
RUBY_TOKENS = re.compile(r"\bdo\b|^[ \t]*(?:if|unless|case|while|until|begin|def|class|module)\b|\bend\b", re.M)
RUBY_DO = re.compile(r"\bdo\b(?:\s*\|[^|\n]*\|)?[ \t]*(?:#[^\n]*)?$", re.M)


def _camel(word: str) -> str:
    """`admin_tools` -> `AdminTools`, `v1` -> `V1`: a Ruby module name from a route namespace."""
    return "".join(x[:1].upper() + x[1:] for x in re.split(r"[_/]", word) if x)


def _ruby_block_end(src: str, at: int) -> int:
    """Where the Ruby `do .. end` block opening on the line of `at` ends (after its `end`), -1 when none opens there
    or it does not close: `do` and the keywords that open a body count up, `end` counts down."""
    eol = src.find("\n", at)
    eol = len(src) if eol < 0 else eol
    if not (m := RUBY_DO.search(src, at, eol + 1)) or m.start() > eol:
        return -1
    depth, i = 0, m.start()
    # strings blanked, length kept: `post 'calls/end'` holds no `end`
    code = re.sub(r"""(["'])(?:\\.|(?!\1)[^\\\n])*\1""", lambda s: s.group(1) + " " * (len(s.group(0)) - 2) + s.group(1),
                  src[i:])
    for tok in RUBY_TOKENS.finditer(code):
        depth += -1 if tok.group(0) == "end" else 1
        if depth == 0:
            return i + tok.end()
    return -1


def _extent(src: str, mount: dict) -> int:
    """Where the code a mount covers ends: its call's closing bracket, a trailing block on the same line
    (`route("/v1") { }`, Ruby `namespace :api do .. end`), and, for a mount without a target (it returns the
    prefixed router), the calls chained on it. -1 when its brackets do not balance."""
    i = mount["call"]
    if i < 0 and (end := _ruby_block_end(src, mount["at"])) >= 0:
        return end
    if i < 0 or (end := _close(src, i)) < 0:
        return -1
    end += 1
    if re.match(r"[ \t]*do\b", src[end:]) and (block := _ruby_block_end(src, end)) >= 0:
        return block   # `namespace(:api) do .. end`
    if (m := re.match(r"[ \t]*\{", src[end:])) and (close := _close(src, end + m.end() - 1)) >= 0:
        end = close + 1
    while mount["target"] is None and (m := CHAIN_STEP.match(src, end)):
        close = _close(src, m.end())
        if close < 0:
            break
        end = close + 1
    return end


def _head(src: str, at: int) -> str | None:
    """The variable a registration is called on: `v1` in `v1.GET(..)`, `api` in `api\n  .route(..)`."""
    if src[at:at + 1] == ".":
        m = HEAD_BEFORE.search(src, max(0, at - 200), at)
        return m.group(1) if m else None
    m = HEAD.match(src, at)
    return m.group(1) if m else None


def _blank_comments(src: str, lang: str) -> str:
    """The source with its comments blanked to spaces (lines and offsets kept), so an apostrophe in one opens no
    string when brackets are matched: `#` comments in Python and Ruby, `//` and `/* */` in the other languages."""
    pat = HASH_COMMENTS if lang in ("python", "ruby") else C_COMMENTS
    return pat.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)) if m.group(1) else m.group(0), src)


def _docstrings(src: str) -> list[tuple[int, int]]:
    """(start, end) offsets of the Python strings that stand alone as a statement (docstrings, prose): a STRING token
    that is a whole logical line, read with `tokenize` so a string's closing quotes on a line of their own, or a
    string passed as an argument, never count. Empty when the source does not tokenize."""
    import io
    import tokenize
    starts = [0]
    for line in src.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    out: list[tuple[int, int]] = []
    try:
        toks = [t for t in tokenize.generate_tokens(io.StringIO(src).readline)
                if t.type not in (tokenize.COMMENT, tokenize.NL)]
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return []
    lead = (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING)
    for i, tok in enumerate(toks):
        if tok.type == tokenize.STRING and (i == 0 or toks[i - 1].type in lead) \
                and i + 1 < len(toks) and toks[i + 1].type in (tokenize.NEWLINE, tokenize.ENDMARKER):
            out.append((starts[tok.start[0] - 1] + tok.start[1], starts[tok.end[0] - 1] + tok.end[1]))
    return out


def pattern_text(src: str, lang: str) -> str:
    """The source every pattern runs on: comments, and Python docstrings, blanked to spaces with lines and offsets
    kept, so a usage example in one is no route, table, queue or job."""
    out = _blank_comments(src, lang)
    if lang == "python":
        for a, b in reversed(_docstrings(src)):
            out = out[:a] + re.sub(r"[^\n]", " ", out[a:b]) + out[b:]
    return out


OWN_PREFIX = {"flask-blueprint-prefix"}   # mounts that set a router's own prefix where it is made


def compose(src: str, routes: list[dict], mounts: list[dict], lang: str = "") -> None:
    """Join each mount's prefix onto the routes registered on it in the same file: inside its call or block, chained
    on it, or called on a variable bound to it (`v1 := r.Group("/v1")`), nested mounts composing outward. Each
    composing mount counts its routes in `composed`. Removes the `at` and `call` positions."""
    src = _blank_comments(src, lang) if mounts else src
    ends = [_extent(src, mt) for mt in mounts]
    bound: dict[str, list[tuple[int, int]]] = {}       # variable -> (where it is bound, the mount)
    for k, mt in enumerate(mounts):
        if mt["target"] is not None or ends[k] < 0:
            continue
        start = mt["at"]
        if src[start:start + 1] == "." and (m := HEAD_BEFORE.search(src, max(0, start - 200), start)):
            start = m.start(1)
        for b in BINDING.finditer(src, max(0, start - 200), start):
            if BOUND_TO.fullmatch(src, b.end(), start):
                bound.setdefault(b.group(1), []).append((b.start(), k))

    def prefix(at: int, head: str | None, depth: int = 0) -> list[int]:
        if depth > 20:
            return []
        inside = [k for k, mt in enumerate(mounts) if mt["at"] < at < ends[k]]
        on = max(((b, k) for b, k in bound.get(head or "", []) if b < at and 0 <= ends[k] <= at),
                 default=(0, None))[1]
        if not inside and on is None:
            return []
        k = max(inside + ([on] if on is not None else []), key=lambda k: mounts[k]["at"])   # the nearest
        return prefix(mounts[k]["at"], _head(src, mounts[k]["at"]), depth + 1) + [k]

    for r in routes:
        if "at" not in r:
            continue
        at = r.pop("at")
        chain = prefix(at, _head(src, at))
        if not chain and (on := _head(src, at)):
            r["on"] = on   # the router it is registered on: a mount in another file may name it (structure)
        if chain and r.get("on_mount"):
            r["composed_on"] = True
        if chain and mounts[chain[0]]["framework"] in OWN_PREFIX and (on := _head(src, at)):
            # `Blueprint(.., url_prefix="/x")` is the router's own prefix: a register call elsewhere may replace it
            r["on"], r["own_prefix"] = on, mounts[chain[0]]["path"]
        if chain:
            r["path"] = normalise("/".join(x.strip("/") for x in [*(mounts[k]["path"] for k in chain), r["path"]]
                                           if x.strip("/")))
            if r.get("handler_class") and (mods := [mounts[k]["module"] for k in chain if mounts[k].get("module")]):
                # a namespace mount names the controllers inside it too (`namespace :api` -> `Api::UsersController`)
                r["handler_class"] = "::".join(_camel(x) for x in mods) + "::" + r["handler_class"]
            for k in chain:
                mounts[k]["composed"] = mounts[k].get("composed", 0) + 1
    for k, mt in enumerate(mounts):
        # a mount handed to a function (`users.Register(v1.Group("/users"))`): its full prefix and that function, for
        # structure to join onto the routes the function registers on its parameter
        if "at" in mt and mt["target"] is None and (passed := PASSED_TO.search(src, max(0, mt["at"] - 200), mt["at"])):
            chain = prefix(mt["at"], _head(src, mt["at"]))
            mt["passed_to"] = passed.group(1)
            mt["full"] = normalise("/".join(x.strip("/") for x in [*(mounts[j]["path"] for j in chain), mt["path"]]
                                            if x.strip("/")))
    for mt in mounts:
        mt.pop("module", None)
        if "at" in mt and (on := _head(src, mt["at"])):
            mt["on"] = on
        mt.pop("at", None)
        mt.pop("call", None)


def find_tables(st: Stack, lang: str, src: str, imports: list[str], spans: list[tuple[int, int, str]],
                class_spans: list[tuple[int, int, str]], file_id: str) -> list[dict]:
    """Table facts from every table pattern of the language that applies to the file. `in` is the innermost
    method around the match (access), else the innermost class (defined), else the file (access)."""
    out = []
    for pat in st.tables:
        if pat.lang != lang or (pat.when and not any(prefix_match(pat.when, i, sep(lang)) for i in imports)):
            continue
        for m in pat.regex.finditer(src):
            if not (table := (m.group("table") or "").strip()):
                continue
            line = src.count("\n", 0, m.start()) + 1
            method = [s for s in spans if s[0] <= line <= s[1]]
            klass = [s for s in class_spans if s[0] <= line <= s[1]]
            if method:
                where, kind = max(method, key=lambda s: s[0])[2], "access"
            elif klass:
                where, kind = max(klass, key=lambda s: s[0])[2], "defined"
            else:
                where, kind = file_id, "access"
            out.append({"table": table, "line": line, "in": where, "kind": kind, "pattern": pat.name,
                        "source": pat.source})
    return out


def find_queues(st: Stack, lang: str, src: str, imports: list[str], spans: list[tuple[int, int, str]],
                file_id: str) -> list[dict]:
    """In-process queue creation sites from every queue pattern of the language that applies to the file. `in` is
    the innermost method around the match, else the file."""
    out = []
    for pat in st.queues:
        if pat.lang != lang or (pat.when and not any(prefix_match(pat.when, i, sep(lang)) for i in imports)):
            continue
        for m in pat.regex.finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            method = [s for s in spans if s[0] <= line <= s[1]]
            out.append({"line": line, "in": max(method, key=lambda s: s[0])[2] if method else file_id,
                        "delivery": pat.delivery, "pattern": pat.name, "source": pat.source})
    return out


def find_jobs(st: Stack, lang: str, src: str, imports: list[str], spans: list[tuple[int, int, str]],
              class_spans: list[tuple[int, int, str]], names: dict[str, str], file_id: str) -> list[dict]:
    """Job system sites from every job pattern of the language that applies to the file (`side`, `job`, `line`,
    `pattern`, `source`). An enqueue's `in` is the innermost method around it, else the file. A definition's or a
    schedule's `node` is, for a decorator or annotation (`@app.task`, `@Scheduled`), the method or class starting
    within 3 lines below it; for any other match (`include Sidekiq::Job`, a class header implementing
    `ShouldQueue`), the class around it; its
    `job` is the pattern's `job` group, else that node's name. A broker message's `publish` is placed like an
    enqueue, its `consume` like a definition but in the method around a call (`consumer.subscribe("x")`); its
    name, the topic or queue, is kept whole: a file constant's value when the group names one, else `$<name>` for a
    value the scan cannot read. `names`: node id -> name."""
    out = []
    constants: dict[str, str] | None = None
    for pat in st.jobs:
        if pat.lang != lang or (pat.when and not any(prefix_match(pat.when, i, sep(lang)) for i in imports)):
            continue
        for m in pat.regex.finditer(src):
            line = src.count("\n", 0, m.start()) + 1
            named = (m.group("job") or "").strip() if "job" in pat.regex.groupindex else ""
            if pat.side in MESSAGE_SIDES:
                if constants is None:
                    constants = file_literals(src)
                quoted = m.start("job") > 0 and src[m.start("job") - 1] in "\"'`"
                if quoted or not re.fullmatch(r"[A-Za-z_$][\w$.]*", named):
                    job = named
                elif named in ("new", "this", "self", "it", "await"):
                    continue   # `kafkaTemplate.send(new ProducerRecord<>(..))`: the record's own pattern names it
                else:   # a name: its literal in the function around, a file constant's, else `$name` (never paired)
                    around = [s for s in spans if s[0] <= line <= s[1]]
                    local = _local_literal(src, named, max(around, key=lambda s: s[0])[0], line + 1) if around else None
                    job = local or constants.get(named.split(".")[-1]) or f"${named}"
            else:
                job = re.split(r"\.|::|\\", named)[-1] if named else ""
            fact = {"side": pat.side, "job": job, "line": line, "pattern": pat.name, "source": pat.source}
            if pat.side == "consume" and not m.group(0).lstrip().startswith("@") \
                    and (method := [s for s in spans if s[0] <= line <= s[1]]):
                fact["node"] = max(method, key=lambda s: s[0])[2]   # `consumer.subscribe("x")` in a method
            elif pat.side in ("enqueue", "publish"):
                method = [s for s in spans if s[0] <= line <= s[1]]
                fact["in"] = max(method, key=lambda s: s[0])[2] if method else file_id
            else:
                around = [s for s in class_spans if s[0] <= line <= s[1]]
                below = sorted(s for s in spans + class_spans if line <= s[0] <= line + 3)
                if m.group(0).lstrip().startswith("@") or not around:   # a decorator or annotation: what it marks
                    # (a class whose span opens at an earlier annotation, `@Component` above it, holds this one)
                    holding = [s for s in spans if s[0] <= line <= s[1]] or around   # `@Override` above `@Scheduled`
                    node = below[0][2] if below else (max(holding, key=lambda s: s[0])[2] if holding else None)
                else:   # a marker inside a class (`include Sidekiq::Job`) or its header: the class
                    node = max(around, key=lambda s: s[0])[2]
                if node is not None:
                    fact["node"] = node
                fact["job"] = job or (names.get(node, "") if node else "")
            if fact["job"]:
                out.append(fact)
    return out


_CLOSE = {"(": ")", "[": "]", "{": "}"}
_ESCAPED = {'"': '"', "'": "'", "\\": "\\", "`": "`", "/": "/"}
_QNAME = r"\\?[A-Za-z_]\w*(?:(?:\.|::|\\)[A-Za-z_]\w*)*"
_ITEM = re.compile(rf"(?:\w+\s*:(?!:)\s*)?({_QNAME})\s*(?:<[^<>()]*>\s*)?")
_NAMED = re.compile(r"([A-Za-z_]\w*)\s*(?:=(?!=)|:(?!:))\s*(.*)", re.S)
_ARRAY = re.compile(r"(?:new\s*(?:\w+\s*)?\[\s*\]\s*|(?:arrayOf|listOf|array)\s*(?=\())")


def _last(name: str) -> str:
    return re.split(r"\.|::|\\", name)[-1]


def _string_at(s: str, i: int) -> tuple[int, str | None] | None:
    """A string literal starting at s[i]: (index after it, its value; None when interpolated), (-1, None) when
    unterminated, None when no string starts there. Text blocks, C# verbatim (`@"..."`) and interpolated
    (`$"..."`) strings, JS template literals (interpolated when they hold `${`)."""
    interp = verbatim = False
    j = i
    while j < len(s) and s[j] in "@$" and j - i < 2:
        interp, verbatim = interp or s[j] == "$", verbatim or s[j] == "@"
        j += 1
    if j >= len(s) or s[j] not in "\"'`" or (j > i and s[j] != '"'):
        return None
    if s.startswith('"""', j):
        end = s.find('"""', j + 3)
        return (-1, None) if end < 0 else (end + 3, None if interp else s[j + 3:end].strip())
    q, out, k = s[j], [], j + 1
    while k < len(s):
        c = s[k]
        if verbatim and c == q:
            if s.startswith(q * 2, k):
                out.append(q)
                k += 2
                continue
            break
        if not verbatim and c == "\\" and k + 1 < len(s):
            out.append(_ESCAPED.get(s[k + 1], c + s[k + 1]))
            k += 2
            continue
        if c == q:
            break
        out.append(c)
        k += 1
    else:
        return -1, None
    value = "".join(out)
    return k + 1, None if interp or (q == "`" and "${" in value) else value


def _close(s: str, i: int) -> int:
    """The index of the bracket closing s[i], skipping strings and nested brackets; -1 when unbalanced."""
    stack_, k = [], i
    while k < len(s):
        if (hit := _string_at(s, k)) is not None:
            if hit[0] < 0:
                return -1
            k = hit[0]
            continue
        c = s[k]
        if c in _CLOSE:
            stack_.append(_CLOSE[c])
        elif c in ")]}":
            if not stack_ or stack_.pop() != c:
                return -1
            if not stack_:
                return k
        k += 1
    return -1


def _split(s: str) -> list[str] | None:
    """Top-level comma-separated pieces (strings and brackets kept whole); None when unbalanced."""
    out, start, k = [], 0, 0
    while k < len(s):
        if (hit := _string_at(s, k)) is not None:
            if hit[0] < 0:
                return None
            k = hit[0]
            continue
        if s[k] in _CLOSE:
            if (end := _close(s, k)) < 0:
                return None
            k = end + 1
            continue
        if s[k] in ")]}":
            return None
        if s[k] == ",":
            out.append(s[start:k])
            start = k + 1
        k += 1
    out.append(s[start:])
    return [x.strip() for x in out if x.strip()] if any(x.strip() for x in out) else []


def _scalar(v: str) -> tuple[str, str]:
    """("str", value) for a string literal, ("name", last segment) for a constant name, else ("other", text)."""
    if (hit := _string_at(v, 0)) is not None and hit[0] == len(v):
        return ("str", hit[1]) if hit[1] is not None else ("other", v)
    if re.fullmatch(_QNAME, v):
        return "name", _last(v)
    return "other", v


def _value(v: str) -> tuple[list[tuple[str, str]], dict[str, list[tuple[str, str]]]]:
    """An argument value as its elements (a scalar is one; an array its elements), and the pairs of an object
    literal (`{ path: 'x' }`), which also count as named arguments."""
    v = v.strip()
    body = v[m.end():] if (m := _ARRAY.match(v)) else v
    if body[:1] in "{[(" and body and _close(body, 0) == len(body) - 1 and (body[0] != "(" or m):
        parts = _split(body[1:-1])
        if parts is None:
            return [("other", v)], {}
        pairs = [_NAMED.fullmatch(x) for x in parts]
        if body[0] == "{" and parts and all(pairs):
            return [("other", v)], {p.group(1): _value(p.group(2))[0] for p in pairs}
        return [_scalar(x) for x in parts], {}
    return [_scalar(v)], {}


Parsed = tuple[str, list[list[tuple[str, str]]], dict[str, list[tuple[str, str]]]]


_GAP = re.compile(r"(?:\s+|//[^\n]*|/\*.*?\*/)*", re.S)


def _groups(t: str) -> list[tuple[list[str] | None, bool]] | None:
    """The top-level attribute groups of a bracketed annotation text, each as (its items, C#): PHP records stacked
    groups (`#[Route('/x')]` then `#[IsGranted('y')]`) as one text, so might a C# `[A] [B]`. None when unreadable."""
    out, k = [], 0
    while k < len(t):
        start = k + 2 if t.startswith("#[", k) else k + 1 if t.startswith("[", k) else -1
        if start < 0 or (end := _close(t, start - 1)) < 0:
            return None
        out.append((_split(t[start:end]), start == k + 1))
        k = _GAP.match(t, end + 1).end()
    return out


def _parse(text: str) -> list[Parsed] | None:
    """Every annotation in one recorded annotation text, its arguments as typed elements; None when unreadable."""
    t = text.strip()
    if t.startswith("[") or t.startswith("#["):
        groups = _groups(t)
    elif t.startswith("@"):
        groups = [([t[1:]], False)]
    else:
        return None
    if not groups or any(not items for items, _ in groups):
        return None
    out = []
    for items, csharp in groups:
        if (one := _parse_items(items, csharp)) is None:
            return None
        out += one
    return out


def _parse_items(items: list[str], csharp: bool) -> list[Parsed] | None:
    out = []
    for item in items:
        if not (m := _ITEM.match(item)):
            return None
        name, rest = _last(m.group(1)), item[m.end():]
        if csharp and name.endswith("Attribute") and name != "Attribute":
            name = name.removesuffix("Attribute")
        positional, named = [], {}
        if rest:
            if not rest.startswith("(") or _close(rest, 0) != len(rest) - 1 or (args := _split(rest[1:-1])) is None:
                return None
            for a in args:
                if nm := _NAMED.fullmatch(a):
                    named[nm.group(1)] = _value(nm.group(2))[0]
                else:
                    elems, pairs = _value(a)
                    positional.append(elems)
                    for k, v in pairs.items():
                        named.setdefault(k, v)
        out.append((name, positional, named))
    return out


def _strings(elems: list[tuple[str, str]]) -> list[str]:
    """The strings of a value made of string literals only; [] when any element is not one."""
    return [v for _, v in elems] if all(k == "str" for k, _ in elems) else []


def parse_annotations(text: str) -> list[tuple[str, list[list[str]], dict[str, list[str]]]]:
    """Every annotation in a recorded annotation text (a C# `[A, B(...)]` or PHP `#[A, B]` list holds several):
    (name, positional values, named values). A name is the last segment of a qualified name; a C# target
    (`[method: X]`) and Kotlin use-site target (`@get:X`) are dropped, as is C#'s `Attribute` suffix. Each value
    is its strings: a literal gives one, an array of literals each; any other value gives []. An object literal
    argument (`@Controller({ path: 'x' })`) also gives its pairs as named values. [] when unreadable."""
    return [(n, [_strings(p) for p in pos], {k: _strings(v) for k, v in named.items()})
            for n, pos, named in _parse(text) or []]


def parse_annotation(text: str) -> tuple[str, list[list[str]], dict[str, list[str]]] | None:
    """The first annotation of parse_annotations, or None."""
    return next(iter(parse_annotations(text)), None)


def _arg_paths(parsed: Parsed, path_args: tuple[str | int, ...]) -> list[str] | None:
    """The paths of the first path argument present (an empty array: [""]); [""] when none is. A constant
    (`RouteKey.Asset`) is a named segment `{Asset}` for the agent to resolve, so its routes stay; None when that
    argument is any other expression."""
    _, positional, named = parsed
    for a in path_args:
        elems = named.get(a) if isinstance(a, str) else (positional[a] if a < len(positional) else None)
        if elems is not None:
            if not all(k in ("str", "name") for k, _ in elems):
                return None
            return [v if k == "str" else "{" + v + "}" for k, v in elems] or [""]
    return [""]


def _alternatives(items: list[tuple[Parsed, int]], path_args: tuple[str | int, ...]) -> list[str] | None:
    """The paths of several annotations as alternatives: [""] for none; None when none of them is literal."""
    if not items:
        return [""]
    out = [p for it, _ in items for p in (_arg_paths(it, path_args) or [])]
    return list(dict.fromkeys(out)) or None


def annotated_routes(pat: AnnotatedPattern, annotations: list[dict], nodes: list[dict]) -> list[dict]:
    """Route facts of one annotated pattern over a file's recorded annotations and nodes: one per method verb
    annotation x class prefix x verb path x method path; a prefix or path that is no literal or constant gives
    none. A verb or method
    path starting with one of the pattern's `absolute` starts drops the class prefix (the start itself is dropped).
    A class carrying one of the pattern's `skip_class` annotations (an HTTP client interface) gives none."""
    by_id = {n["id"]: n for n in nodes}
    on: dict[str, list[tuple[Parsed, int]]] = {}
    for a in annotations:
        for parsed in _parse(a["text"]) or []:
            on.setdefault(a["node"], []).append((parsed, a["line"]))
    out, seen = [], set()
    for n in nodes:
        if n["kind"] != "method":
            continue
        mine = on.get(n["id"], [])
        verbs = [(it, line) for it, line in mine if it[0] in pat.verbs]
        if not verbs:
            continue
        owner = by_id.get(n["parent"])
        klass = owner if owner is not None and owner["kind"] == "class" else None
        if klass and any(x[0][0] in pat.skip_class for x in on.get(klass["id"], [])):
            continue
        prefixes = _alternatives([x for x in on.get(klass["id"], []) if x[0][0] in pat.prefix] if klass else [],
                                 pat.path_args)
        tails = _alternatives([x for x in mine if x[0][0] in pat.method_path], pat.path_args)
        if prefixes is None or tails is None:
            continue
        for verb, line in verbs:
            paths = _arg_paths(verb, pat.path_args)
            if paths is None:
                continue
            if (how := pat.verbs[verb[0]]) == FROM_ARG:
                elems = verb[2].get(pat.method_arg or "method", [])
                how = list(dict.fromkeys(verb_of(v) or _last(v).upper()
                                         for k, v in elems if k in ("str", "name") and v)) or ["ANY"]
            else:
                how = [how]
            for pre in prefixes:
                for path in paths:
                    for tail in tails:
                        parts = [pre, path, tail]
                        for i in (1, 2):
                            if hit := next((a for a in pat.absolute if parts[i].startswith(a)), None):
                                parts[:i + 1] = [""] * i + [parts[i][len(hit):]]
                        raw = "/".join(x.strip("/") for x in parts if x.strip("/"))
                        for tok, repl in pat.token.items():
                            if repl == "class-stem" and klass:
                                raw = raw.replace(tok, re.sub(r"Controller$", "", klass["name"]))
                            elif repl == "method-name":
                                raw = raw.replace(tok, n["name"])
                        for method in how:
                            key = (method, normalise(raw), n["id"])
                            if key not in seen:
                                seen.add(key)
                                out.append({"method": method, "path": key[1], "handler": n["id"], "line": line,
                                            "framework": pat.name, "source": pat.source})
    return out


def find_annotated(st: Stack, lang: str, annotations: list[dict], nodes: list[dict], imports: list[str]) -> list[dict]:
    """Route facts from every annotated pattern of the language that applies to the file (imports: import_names)."""
    out = []
    for pat in st.patterns:
        if isinstance(pat, AnnotatedPattern) and pat.lang == lang \
                and (not pat.when or any(prefix_match(pat.when, i, sep(lang)) for i in imports)):
            out += annotated_routes(pat, annotations, nodes)
    return out


BUILT_IN = {"fastapi": "python", "tapir": "scala"}   # route rules kept in code, counted in the pattern report
SERVER_KINDS = ("http-in", "http")
# a line that looks like a route registration in a server file: an HTTP verb, `route`, `match` or `any` called or
# annotated with a path (`.get("/x"`, `@Post("/x"`, `@GetMapping("/x"`, `->get("/x"`), or a resource route
# (`Route::apiResource('songs'`, `resources :orders`)
ROUTE_LIKE = re.compile(
    r"(?:[.@]|::|->)\s*(?i:(?:get|post|put|patch|delete|options|head|any|match|route|api_route)(?:mapping)?)"
    r"\s*\(\s*(?:\[[^\]\n]*\]\s*,\s*)?[\"'`]/[^\"'`\n]*[\"'`]"
    r"|(?:::|\.)\s*(?:apiResources?|resources?)\s*\(\s*[\"'][\w./-]+[\"']|^\s*resources?\s+:\w+", re.M)


def route_like(src: str, lang: str) -> list[dict]:
    """The lines of a server file that look like route registrations (ROUTE_LIKE), comments left out. A decorator
    or annotation line also carries `decorates`: the line of what it decorates, where a route on it is recorded."""
    clean = _blank_comments(src, lang)
    lines = src.split("\n")
    seen: dict[int, dict] = {}
    for m in ROUTE_LIKE.finditer(clean):
        line = clean.count("\n", 0, m.start()) + 1
        if line in seen:
            continue
        seen[line] = {"line": line, "text": lines[line - 1].strip()[:120]}
        if lines[line - 1].lstrip().startswith("@"):
            nxt = line
            while nxt < len(lines) and (not lines[nxt].strip() or lines[nxt].lstrip().startswith(("@", "#", "//"))
                                        or _open_brackets(lines[line - 1:nxt]) > 0):
                nxt += 1
            seen[line]["decorates"] = nxt + 1
    return list(seen.values())


def _open_brackets(lines: list[str]) -> int:
    """How many brackets the lines leave open: a decorator's arguments may run over several lines."""
    text = "\n".join(lines)
    return sum(text.count(c) for c in "([{") - sum(text.count(c) for c in ")]}")


DB_KINDS = ("sql-db", "doc-db")
# a class that looks like a database entity: annotated as one, or extending an ORM's model base
ENTITY_ANNOTATION = re.compile(r"^@?(?:[\w.]+\.)?(?:Entity|Table|Document|SqlName|Collection|Schema|Model)\b")
ENTITY_KEYWORD = re.compile(r"^table\s*=\s*True$")   # SQLModel's `class User(UserBase, table=True)`
ENTITY_BASES = {"Model", "Entity", "Document", "Base", "DeclarativeBase", "ApplicationRecord",
                "ActiveRecord::Base", "BaseEntity", "Eloquent"}


def entities_without_table(r: dict, imports_db: bool) -> list[dict]:
    """The classes of a file that look like database entities (ENTITY_ANNOTATION, ENTITY_BASES) where no table
    pattern gave a table: their table comes from a naming default or a style no pattern reads."""
    if not imports_db:
        return []
    tabled = {t.get("in") for t in r.get("tables", [])}
    marked = {a["node"] for a in r.get("annotations", []) if ENTITY_ANNOTATION.match(a["text"])}
    marked |= {cid for cid, kws in r.get("class_keywords", {}).items() if any(ENTITY_KEYWORD.match(k) for k in kws)}
    for cid, supers in r.get("supers", []) + r.get("bases", []):
        if any(re.split(r"[.\\]", x)[-1] in ENTITY_BASES or x in ENTITY_BASES for x in supers):
            marked.add(cid)
    return [{"class": n["name"], "line": n["line"]} for n in r["nodes"]
            if n["kind"] == "class" and n["id"] in marked and n["id"] not in tabled]


def _untabled(files: dict[str, dict]) -> list[dict]:
    return [{"lang": f["lang"], "file": path, "classes": [x["class"] for x in f["untabled"]],
             "lines": [x["line"] for x in f["untabled"]]}
            for path, f in sorted(files.items()) if f.get("untabled")]


def _unmatched_routes(files: dict[str, dict]) -> list[dict]:
    """Per server file, the route-looking lines (route_like) no route or mount came from: a route style the
    patterns miss."""
    out = []
    for path, f in sorted(files.items()):
        done = {r["line"] for r in f["routes"]} | {m["line"] for m in f["mounts"]}
        if left := [x for x in f.get("route_like", []) if x["line"] not in done and x.get("decorates") not in done]:
            out.append({"lang": f["lang"], "file": path, "lines": [x["line"] for x in left], "example": left[0]["text"]})
    return out


GROUP_DEPTH = {"python": 1, "scala": 2, **{spec.lang: spec.group_depth for spec in ALL}}


def _prefix(lang: str, target: str) -> str:
    """The library an import belongs to: the language's `group_depth` segments; an npm `@scope/name` is two,
    a Go path without a host (no dot in its first segment) one. A leading separator (Rust `::serde`) is dropped."""
    s = sep(lang)
    parts = target.removeprefix(s).split(s)
    depth = GROUP_DEPTH[lang]
    if s == "/" and parts[0].startswith("@"):
        depth = 2
    elif lang == "go" and "." not in parts[0]:
        depth = 1
    return s.join(parts[:depth])


def _index(internal: set[str], separator: str = ".") -> tuple[set[str], set[str]]:
    """(internal names, every proper prefix of them): built once, so a lookup is a few set probes."""
    above = set()
    for n in internal:
        parts = n.split(separator)
        above.update(separator.join(parts[:i]) for i in range(1, len(parts)))
    return set(internal), above


def _is_internal(target: str, index: tuple[set[str], set[str]], separator: str = ".") -> bool:
    """The target is, sits under, or is a parent of an internal name."""
    names, above = index
    if target in above:
        return True
    parts = target.split(separator)
    return any(separator.join(parts[:i]) in names for i in range(1, len(parts) + 1))


def _declared(name: str, src: str) -> bool:
    n = re.escape(name)
    return bool(re.search(rf"\b(?:val|var|def|lazy val|object|class|trait|given|case class)\s+{n}\b|\b{n}\s*(?::|<-)", src))


def _local_scala(target: str, src: str, package: str, index: tuple[set[str], set[str]]) -> bool:
    """An import of something the repo defines: a capitalised name, one declared in the importing file, or
    a package relative to the file's own (`import model.User` inside `package com.acme` is `com.acme.model`)."""
    first = target.split(".")[0]
    if first[:1].isupper() or _declared(first, src):
        return True
    parts = package.split(".") if package and package != "_root_" else []
    names, above = index
    return any((c := ".".join(parts[:i] + [first])) in names or c in above for i in range(1, len(parts) + 1))


# a build tool's own config file (`webpack.config.js`, `vite.config.ts`, `.eslintrc.cjs`, `gulpfile.js`)
BUILD_CONFIG = re.compile(r"(?:^|/)(?:(?:webpack|vite|vitest|rollup|babel|jest|eslint|prettier|postcss|tailwind|svelte"
                          r"|next|nuxt|astro|playwright|cypress|karma|stylelint|commitlint|lint-staged)\.config"
                          r"(?:\.\w+)?\.[cm]?[jt]s|\.eslintrc\.[cm]?js|gulpfile\.[jt]s|Gruntfile\.js)$")
# what an unrecognised library looks like by its name, so the ones that change the map are sorted first
LOOKS_LIKE = (("server", re.compile(r"server|http|express|hono|fastify|koa|flask|fastapi|gin|"
                                    r"echo|fiber|actix|axum|rocket|ktor|sinatra|graphql|"
                                    r"grpc|socket(io)?|ws|websockets?|starlette|sanic|tornado|aiohttp|hapi|elysia")),
              ("datastore", re.compile(r"sql\w*|\w*sql|mongo\w*|redis|db|database|orm|prisma|typeorm|sequelize|"
                                       r"diesel|jdbc|jpa|hibernate|cassandra|dynamo\w*|elastic\w*|knex|drizzle")),
              ("queue", re.compile(r"kafka\w*|amqp\w*|rabbit\w*|queue|bull\w*|sqs|pubsub|nats|celery|sidekiq")),
              ("client", re.compile(r"client|sdk|axios|okhttp|feign|reqwest|requests|httpx|got|ky")))


def _looks_like(prefix: str) -> str | None:
    words = [w for w in re.split(r"[^a-z0-9]+", prefix.lower()) if w]
    return next((kind for kind, rx in LOOKS_LIKE if any(rx.fullmatch(w) for w in words)), None)


def _unrecognised(st: Stack, files: dict[str, dict], internal: dict[str, set[str]]) -> list[dict]:
    """internal: language -> the import names of the repo's own code in that language. Language items are no
    library: a PHP name with no namespace (`use Exception;`), a Rust path from a type (`use SortType::*`). A
    prefix that would cover the repo's own package too (`com.acme` beside `com.acme.shop`) takes one more
    segment. Libraries whose name looks like a server, datastore, queue or client come first."""
    seen: dict[tuple[str, str], dict[str, int]] = {}
    indexes: dict[str, tuple[set[str], set[str]]] = {}
    for path in sorted(files):
        f = files[path]
        lang, s = f["lang"], sep(f["lang"])
        if lang not in indexes:
            indexes[lang] = _index(internal.get(lang, set()), s)
        index = indexes[lang]
        for imp in f["imports"]:
            t = imp["target"]
            if imp["relative"]:
                continue
            if lang == "python" and t.split(".")[0] in sys.stdlib_module_names:
                continue
            if lang == "go" and "." not in t.split("/")[0]:
                continue      # the standard library: no host in the path
            if lang in ("typescript", "javascript") and t.startswith(("/", "$")):
                continue      # rooted at the project (Vite `/src/main`) or a bundler alias (`$lib`): the repo's own
            if BUILD_CONFIG.search(path):
                continue      # a build tool's config file imports its plugins, not the app's libraries
            if lang == "php" and "\\" not in t.lstrip("\\") and not imp.get("names"):
                continue      # a global class: `use Exception;`
            if lang == "rust" and t.split("::")[0][:1].isupper():
                continue      # `use SortType::*`, `use Self::Kind`: an item in scope, not a crate
            if _is_internal(t, index, s):
                continue
            if lang == "scala" and _local_scala(t, f.get("src", ""), f.get("package", ""), index):
                continue
            if not all(covered(st, lang, x) for x in targets(imp, lang)):
                prefix, parts = _prefix(lang, t), t.removeprefix(s).split(s)
                while prefix in index[1] and prefix != t:   # it would ignore the repo's own package too
                    prefix = s.join(parts[:len(prefix.split(s)) + 1])
                seen.setdefault((lang, prefix), {}).setdefault(path, imp["line"])
    out = [{"lang": lang, "prefix": prefix, "files": len(at), "examples": [f"{p}:{n}" for p, n in list(at.items())[:2]],
            **({"looks_like": kind} if (kind := _looks_like(prefix)) else {})}
           for (lang, prefix), at in sorted(seen.items())]
    return sorted(out, key=lambda u: "looks_like" not in u)


def _servers(st: Stack, files: dict[str, dict]) -> list[dict]:
    libs: dict[tuple[str, str], dict] = {}
    for path, f in files.items():
        for imp in f["imports"]:
            for hit in import_sinks(st, f["lang"], imp):
                if hit["kind"] in SERVER_KINDS:
                    e = libs.setdefault((f["lang"], hit["lib"]), {"kind": hit["kind"], "files": set()})
                    e["files"].add(path)
    return [{"lang": lang, "prefix": lib, "kind": e["kind"], "files": len(e["files"])}
            for (lang, lib), e in sorted(libs.items())
            if not any(prefix_match(i, lib, sep(lang)) or prefix_match(lib, i, sep(lang))
                       for i in st.stack_ignore.get(lang, []))
            and not any(f["routes"] for f in files.values() if f["module"] in {files[p]["module"] for p in e["files"]})]


def _patterns(st: Stack, files: dict[str, dict], langs: set[str]) -> list[dict]:
    def entry(group, lang, name, source, hits, first):
        return {"group": group, "lang": lang, "name": name, "source": source, "matches": len(hits),
                "files": len({p for p, _ in hits}), "first_file": first}

    def hits_of(group, lang, name):
        return [(p, r) for p, f in sorted(files.items()) if f["lang"] == lang
                for r in f.get(group, []) if (r["framework"] if group in ("routes", "mounts") else r["pattern"]) == name]

    out = []
    for name, lang in BUILT_IN.items():
        if hits := hits_of("routes", lang, name):
            out.append(entry("routes", lang, name, "built in", hits, hits[0][0]))
    for group, pats in (("routes", st.patterns), ("tables", st.tables), ("queues", st.queues), ("jobs", st.jobs)):
        for pat in pats:
            if pat.lang not in langs:
                continue
            users = [p for p, f in sorted(files.items()) if f["lang"] == pat.lang
                     and (not pat.when or _when_line(pat.when, f["imports"], pat.lang) is not None)]
            if pat.source != "stack.yaml" and not users:
                continue
            if users and pat.when:
                line = _when_line(pat.when, files[users[0]]["imports"], pat.lang)
                first = f"{users[0]}:{line}"
            elif users:
                first = users[0]
            else:
                first = next(p for p, f in sorted(files.items()) if f["lang"] == pat.lang)
            mount = isinstance(pat, RoutePattern) and pat.mount
            hits = hits_of("mounts" if mount else group, pat.lang, pat.name)
            if pat.source == "pack" and not pat.when and not hits:
                continue   # a pack pattern every file of the language could match: listed where it matched
            out.append(entry(group, pat.lang, pat.name, pat.source, hits, first))
            if mount:
                out[-1]["mount"] = True
            if isinstance(pat, AnnotatedPattern):
                out[-1]["form"] = "annotated"
            if not out[-1]["matches"] and (by := [k for f in files.values() if f["lang"] == pat.lang
                                                  for g, n, k in f.get("deduped", []) if g == group and n == pat.name]):
                out[-1]["duplicates"] = max(dict.fromkeys(by), key=by.count)   # every match was another pattern's
    return sorted(out, key=lambda e: e["lang"])


def report(st: Stack, files: dict[str, dict], internal: dict[str, set[str]], langs: set[str]) -> dict:
    """The Stack block of structure.json: what no pack or stack.yaml covers, and how each route pattern did."""
    return {"digest": st.digest, "unrecognised": _unrecognised(st, files, internal),
            "servers_without_routes": _servers(st, files), "routes_unmatched": _unmatched_routes(files),
            "entities_without_table": _untabled(files),
            "patterns": _patterns(st, files, langs),
            "overrides": list(st.overrides)}


def flagged(p: dict) -> bool:
    """A stack.yaml pattern that matched nothing (one whose matches another pattern also gave is a duplicate,
    not flagged); pack patterns are only counted."""
    return p["matches"] == 0 and p["source"] == "stack.yaml" and not p.get("duplicates")


def count(rep: dict) -> int:
    return len(rep["unrecognised"]) + len(rep["servers_without_routes"]) + len(rep.get("routes_unmatched", [])) \
        + sum(1 for p in rep["patterns"] if flagged(p))
