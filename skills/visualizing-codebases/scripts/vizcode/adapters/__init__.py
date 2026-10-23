"""Per-language parsers. Each returns a FileResult dict:

nodes     code-map nodes for this file (file/class/method; package node built by the caller)
package   dotted package name the file belongs to
imports   [{target, line, relative, names?}]   names: imported member names (Python from-imports, generic)
          renames?: {local name: member name} (Scala `{A => B}`, every `as` alias of a member); as?: the local
          name of a whole-module import
          (TS `import * as m`, Python `import a.b as m`, Go `m "path"`)
aliases   [name]  type names the file declares that are no class (type aliases, Python module-level type
          assignments and TypeVars): a type link never resolves them
calls     [{callee, in, line}]
strings   [{text, line, in}]           literal contents, interpolations as {..}
env_keys  [{key, line}]
routes    [{method, path, handler, line, framework}]
includes  [{app, router, prefix, line}]   FastAPI include_router calls (Python only)
tapir     {"vals": {qualname: {...}}, "bodies": [(method_id, line, body_text)], "root": imports sttp.tapir,
           "client": imports sttp.tapir.client, "named": {body index: qualified val name},
           "binds": [(method_id, endpoint as written, line)] server logic bound to an endpoint,
           "mentions"?: [dotted names] in a file importing an sttp client,
           "consts"?: {name: text} the file's string constants, for a path segment written as one}  (Scala only)
supers    [(class_id, [type name as written])]  what a class extends or an anonymous body implements (Scala, generic)
bodyless? [method_id]  methods declared without a body (an interface's, an abstract one) (generic)
bases     [(class_id, [base as written])]  a class's bases (Python only; gRPC servicers and `implements`)
dags      [{framework, id, schedule, tasks, node, line}]  Airflow DAGs: `@dag` functions, `with DAG(...)` blocks (Python)
workflows [{framework, id, node, line, launch_plans: [{name, schedule, line}]}]  Flyte workflows (Python)
reference_tasks [{kind, project, domain, name, node, line}]  Flyte reference_task/workflow/launch_plan (Python)
annotations [{node, text, line}]  annotations/decorators on class and method nodes (generic walker)
nested    [{name, start, line, end, in, params}]  named functions inside a function (`in`), not nodes: structure makes
          one a node when a route names it (start: its first decorator's line, else line)
attached  [class node]  types this file's methods attach to (Go receivers, Rust `impl`) but no class here declares;
          structure.build counts them on the declared class, else adds the node (generic walker)
package_declared  a declared package name other than the folder's last segment (Go), kept as is; absent when equal
parse_error  bool
"""
from __future__ import annotations

import re

from .langs import BY_SUFFIX

SOURCE_SUFFIXES = (".py", ".scala", *BY_SUFFIX)


def without_suffix(name: str) -> str:
    """`repo.py` -> `repo`, `Repo.java` -> `Repo`: a file name without its source suffix."""
    return next((name[:-len(s)] for s in SOURCE_SUFFIXES if name.endswith(s)), name)


def decode(raw: bytes) -> str:
    """UTF-8, or cp1252 for older files: a replacement character would cut identifiers like `té` short."""
    try:
        return raw.decode("utf8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", "replace")


def arg_count(call, splats: tuple[str, ...]) -> int | None:
    """Arguments passed at a call site, or None when a splat (`*xs`, `**kw`, `xs: _*`) hides the count."""
    return count_args(call.child_by_field_name("arguments"), splats)


def count_args(args, splats: tuple[str, ...], comments: tuple[str, ...] = ("comment",)) -> int | None:
    """Arguments in an argument list node (None: no list, or a splat hides the count)."""
    if args is None:
        return None
    named = [a for a in args.named_children if a.type not in comments]
    if any(a.type in splats for a in named):
        return None
    return len(named)


def text(node) -> str:
    return decode(node.text)


CALLEE_MAX = 120
_QUOTED = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def callee_text(callee: str) -> str:
    """A call's callee as recorded, at most CALLEE_MAX characters. A longer one (a fluent chain, long arguments) first
    loses its literals and bracketed argument text, then its head, never the called name at its end; a cut head
    starts with `()`, which call resolution reads as an untrusted receiver."""
    if len(callee) <= CALLEE_MAX:
        return callee
    out, depth = [], 0
    for ch in _QUOTED.sub('""', callee):
        if ch in "([{":
            depth += 1
            if depth == 1:
                out.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            if depth == 0:
                out.append(ch)
        elif depth == 0:
            out.append(ch)
    short = re.sub(r" ?([^\w ]) ?", r"\1", re.sub(r"\s+", " ", "".join(out)).strip())
    return short if len(short) <= CALLEE_MAX else "()" + short[-(CALLEE_MAX - 2):]


def new_result(package: str, parse_error: bool) -> dict:
    return {"nodes": [], "package": package, "imports": [], "calls": [], "strings": [],
            "env_keys": [], "routes": [], "includes": [], "tapir": {"vals": {}, "bodies": [], "root": False, "client": False}, "supers": [],
            "aliases": [], "type_params": {}, "nested": [], "parse_error": parse_error}


TYPE_PARAM_LISTS = frozenset({"type_parameters", "type_parameter_list", "type_parameter"})   # Python's is the last
_NAMES = frozenset({"identifier", "type_identifier", "simple_identifier"})
_WRAPS = frozenset({"type", "constrained_type", "splat_type"})


def _leading_names(item) -> list[str]:
    """The names a type parameter entry declares: its leading identifiers (Go `T, U any`), inside a wrapper
    (Python `T: int`, `*Ts`), never its bound."""
    if item.type in _NAMES:
        return [text(item)]
    names: list[str] = []
    for c in item.named_children:
        if c.type in _NAMES:
            names.append(text(c))
        elif c.type in _WRAPS and not names:
            return _leading_names(c)
        elif not any(w in c.type for w in ("modifier", "annotation", "attribute")):   # `@Ann T`, C# `[Foo] T`
            break
    return names


def declared_type_params(fn) -> list[str]:
    """Names of the type parameters a function and the declarations around it declare (`<TEvent>`, `[T any]`,
    `impl<T>`, a class's `[A]`), and those a Go receiver binds (`func (b *Bus[TEvent])`), sorted."""
    out: set[str] = set()
    n = fn
    while n is not None:
        for plist in n.named_children:
            if plist.type in TYPE_PARAM_LISTS and (plist.type != "type_parameter" or plist.parent.type in (
                    "function_definition", "class_definition", "type_alias_statement")):
                for item in plist.named_children:
                    if item.type in _NAMES or item.type in _WRAPS or item.type.endswith(
                            ("type_parameter", "type_parameter_declaration")):
                        out.update(_leading_names(item))
        n = n.parent
    receiver = fn.child_by_field_name("receiver")
    for args in walk(receiver) if receiver is not None else ():
        if args.type == "type_arguments":
            out.update(text(t) for t in walk(args) if t.type == "type_identifier")
    return sorted(out)


def make_node(nid: str, kind: str, parent: str, name: str, lang: str, file: str, ts_node,
              visibility: str = "public") -> dict:
    return {"id": nid, "kind": kind, "parent": parent, "name": name, "lang": lang, "file": file,
            "line": ts_node.start_point[0] + 1, "visibility": visibility,
            "metrics": {"loc": ts_node.end_point[0] - ts_node.start_point[0] + 1}}


def enclosing_id(node, scope_ids: dict[int, str]) -> str | None:
    p = node.parent
    while p is not None:
        if p.start_byte in scope_ids and p.type in ("function_definition", "function_declaration", "val_definition"):
            return scope_ids[p.start_byte]
        p = p.parent
    return None


def walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))
