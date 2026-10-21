"""Scala 3: package clauses, class/object/trait/enum, defs; tapir and zio-http routes."""
from __future__ import annotations

import functools
import re
from pathlib import PurePosixPath

from tree_sitter_language_pack import get_parser

from .. import ids, routes, stack
from . import (arg_count, callee_text, declared_type_params, decode, enclosing_id, fields, make_node, new_result,
               text, walk)

PARSER = get_parser("scala")
CLASS_KINDS = {"class_definition": "", "trait_definition": "", "enum_definition": "", "object_definition": "$"}
FN_KINDS = ("function_definition", "function_declaration")
ENV = re.compile(r'(?:sys\.env\.get|sys\.env|System\.getenv)\(\s*"([A-Za-z0-9_]+)"')
INTERP = re.compile(r"#?\$\{([^}]*)\}|#?\$([A-Za-z_]\w*)")
# a `val` member holds behaviour when its type or value is an effect, layer, stream or a function;
# the effect type names come from the packs and stack.yaml
OPERATORS = r"\.\s*(provide\w*|fork\w*)\b|\*>|<\*"
SERVER_LOGIC = r"(?<![\w.]){}\s*\.\s*z?[sS]erverLogic"
# `X.endpoint.zServerLogic(..)`, `.serverSecurityLogic..`: the endpoint a body binds server logic to
BINDS = re.compile(r"(?<![\w.])([A-Za-z_][\w.]*?)\s*\.\s*z?[sS]erver(?:Security)?Logic\w*")
DOTTED = re.compile(r"(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")


def _visibility(node) -> str:
    for c in node.named_children:
        if c.type == "modifiers" and re.search(r"\b(private|protected)\b", text(c)):
            return "private"
    return "public"


LITERALS = {"string", "interpolated_string_expression", "integer_literal", "floating_point_literal",
            "boolean_literal", "character_literal", "null_literal", "unit"}
STRING_LIT = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"')


@functools.lru_cache(maxsize=None)
def _effect_patterns(effects: tuple[tuple[str, ...], tuple[str, ...]]) -> tuple[re.Pattern, re.Pattern]:
    types, values = effects
    typ = re.compile(r"^(?:[\w.]+\.)?(" + "|".join(map(re.escape, types)) + r")\b") if types else re.compile(r"(?!)")
    head = r"(?<![\w.])(" + "|".join(map(re.escape, values)) + r")\s*[.(:\[]|" if values else ""
    return typ, re.compile(head + OPERATORS)


def _behaviour(typ, val, effects) -> bool:
    """Effects, layers, streams and function literals; constants (even a string mentioning `ZIO.`) and
    endpoint descriptions are not."""
    effect_type, effect_value = _effect_patterns(effects)
    if typ is not None and (effect_type.match(text(typ)) or "=>" in text(typ)):
        return True
    if val.type in LITERALS:
        return False
    return val.type == "lambda_expression" or effect_value.search(STRING_LIT.sub('""', text(val))) is not None


def _type_names(node) -> list[str]:
    """Simple or dotted names of the types a class extends or `new` instantiates, without type arguments."""
    if node is None:
        return []
    if node.type in ("type_identifier", "stable_type_identifier"):
        return [text(node)]
    if node.type == "generic_type":
        return _type_names(node.named_children[0] if node.named_children else None)
    if node.type in ("compound_type", "extends_clause"):
        out = []
        for i, ch in enumerate(node.children):
            if node.type == "extends_clause" and node.field_name_for_child(i) != "type":
                continue
            out += _type_names(ch)
        return out
    return []


def _anonymous(node):
    """Outermost `new T { ... }` / `new T:` bodies under node (nested ones are found when their
    enclosing body is visited)."""
    stack = [node]
    while stack:
        n = stack.pop()
        if n.type == "instance_expression":
            body = next((c for c in n.named_children if c.type == "template_body"), None)
            if body is not None:
                yield n, body
                continue
        stack.extend(reversed(n.named_children))


def _params(fn, field: str = "parameters", kind: str = "parameter") -> list[dict]:
    """Every parameter list's parameters (a class's: `class_parameters`, `class_parameter`); `optional` marks one a
    call may leave out: a default value, a later (curried) list, a `using` or `implicit` list."""
    out = []
    lists = [p for p in fn.children_by_field_name(field) if p.type != "type_parameters"]
    for i, plist in enumerate(lists):
        given = re.match(r"\(\s*(?:using|implicit)\b", text(plist)) is not None
        for p in plist.named_children:
            if p.type != kind:
                continue
            name, typ = p.child_by_field_name("name"), p.child_by_field_name("type")
            out.append({"name": text(name) if name else "_", "type": text(typ) if typ else None})
            if i or given or p.child_by_field_name("default_value") is not None:
                out[-1]["optional"] = True
    return out


def _package(root) -> str:
    parts = []
    for c in root.named_children:
        if c.type == "package_clause":
            name = c.child_by_field_name("name")
            parts.append(re.sub(r"\s+", "", text(name)))
    return ".".join(parts) or "_root_"


def _string_body(n) -> str | None:
    raw = text(n)
    if n.type == "interpolated_string_expression":
        raw = re.sub(r"^\w+", "", raw)
    m = re.match(r'^("""|")(.*)\1$', raw, re.S)
    if not m:
        return None
    return INTERP.sub(lambda x: "{" + (x.group(1) or x.group(2)).strip() + "}", m.group(2)) if n.type == "interpolated_string_expression" else m.group(2)


def _import_targets(decl_text: str) -> list[tuple[str, list[str], dict[str, str]]]:
    """(target, names, {local name: name}) per import clause: `a.b.C` -> (a.b.C, [], {}); `a.b.{C, D => E, _}`
    -> (a.b, [C, D], {E: D}) and, for the wildcard, (a.b, [], {}); `{X => _}` hides X."""
    body = decl_text.removeprefix("import")
    braces = {}
    body = re.sub(r"\{([^}]*)\}", lambda m: braces.setdefault(f"@{len(braces)}", m.group(1)) and f"@{len(braces) - 1}",
                  body)
    out = []
    for t in body.split(","):
        t = re.sub(r"\s+", "", t)
        names, renames, wildcard = [], {}, False
        if m := re.search(r"\.(@\d+)$", t):
            t = t[: m.start()]
            for item in braces[m.group(1)].split(","):
                parts = re.split(r"\s*(?:=>|\bas\b)\s*", item.strip())
                name = parts[0].strip("` ")
                if name in ("_", "*") or name.startswith("given"):
                    wildcard = True
                elif re.fullmatch(r"[A-Za-z_]\w*", name):
                    local = parts[1].strip("` ") if len(parts) > 1 else name
                    if local != "_":
                        names.append(name)
                        if local != name:
                            renames[local] = name
        t = re.sub(r"(\.(\*|_|given))+$", "", t).rstrip(".")
        if re.fullmatch(r"[A-Za-z_][\w.]*", t):
            if names:
                out.append((t, names, renames))
            if wildcard or not names:
                out.append((t, [], {}))
    return out


def _arg_count(call) -> int | None:
    """Arguments at a call site; a Scala 3 colon lambda (`db.transaction: c =>`) is one, whatever its body holds."""
    args = call.child_by_field_name("arguments")
    if args is not None and args.type == "colon_argument":
        return 1
    return arg_count(call, ("repeated_parameter_type", "ascription_expression"))


def parse(src: bytes, rel_file: str, module: dict, reg: ids.IdRegistry, st: stack.Stack | None = None) -> dict:
    effects = stack.effect_names(st or stack.default(), "scala")
    tree = PARSER.parse(src)
    root = tree.root_node
    pkg = _package(root)
    res = new_result(pkg, root.has_error)
    mid = module["id"]
    pkg_id = ids.package_id(mid, pkg)
    scope_ids: dict[int, str] = {}
    method_bodies: list[tuple[str, str]] = []     # (method id, body text) of defs
    val_bodies: list[tuple[int, str, str]] = []   # (index in tapir bodies, val name, qualified name)
    starts: list[int] = []                        # the line each tapir body's text starts on
    def_names: dict[int, str] = {}                # index in tapir bodies -> qualified name, for defs
    unnamed: dict[str, int] = {}                  # anonymous implementations per owner, for `$impl<n>`
    file_holder: list[dict] = []

    def file_node() -> dict:
        if not file_holder:
            fid = reg.claim(f"{pkg_id}{PurePosixPath(rel_file).name}")
            n = make_node(fid, "file", pkg_id, PurePosixPath(rel_file).name, "scala", rel_file, root)
            n["metrics"]["methods"] = 0
            res["nodes"].append(n)
            file_holder.append(n)
        return file_holder[0]

    def visit(container, owner: dict | None, qual: list[str]) -> None:
        for c in container.named_children:
            if c.type == "package_clause":
                body = c.child_by_field_name("body")
                if body is not None:
                    visit(body, owner, qual)
            elif c.type in CLASS_KINDS:
                name_node = c.child_by_field_name("name")
                if name_node is None:
                    continue
                name = text(name_node)
                cq = qual + [name]
                cid = reg.claim(ids.qualified(mid, (pkg + "." if pkg != "_root_" else "") + ".".join(cq) + CLASS_KINDS[c.type]))
                n = make_node(cid, "class", owner["id"] if owner and owner["kind"] == "class" else pkg_id,
                              name, "scala", rel_file, c, _visibility(c))
                n["metrics"]["methods"] = 0
                if found_fields := fields.scala(c):
                    n["fields"] = found_fields
                if c.type == "class_definition" and not any(k.type == "case" for k in c.children) \
                        and (plist := c.child_by_field_name("class_parameters")) is not None:
                    # a class that is no case class: its parameters are what it is built from
                    n["ctor"] = {"params": _params(c, "class_parameters", "class_parameter"),
                                        "line": plist.start_point[0] + 1}
                    if tps := declared_type_params(c):
                        res["type_params"][cid] = tps
                res["nodes"].append(n)
                if supers := _type_names(c.child_by_field_name("extend")):
                    res["supers"].append((cid, supers))
                body = c.child_by_field_name("body")
                if body is not None:
                    visit(body, n, cq)
            elif c.type in FN_KINDS:
                name_node = c.child_by_field_name("name")
                if name_node is None:
                    continue
                params = _params(c)
                body = c.child_by_field_name("body")
                if not params and body is not None and (hit := routes.tapir_val(
                        qual, text(name_node), text(body), key=".".join(qual) if text(name_node) == "apply" else None)):
                    res["tapir"]["vals"][hit[0]] = hit[1]   # `def v1() = base.in("v1")`: also a prefix, as a val
                parent = owner if owner is not None else file_node()
                fid = reg.claim(ids.method_id(parent["id"], text(name_node), len(params)))
                ret = c.child_by_field_name("return_type")
                n = make_node(fid, "method", parent["id"], text(name_node), "scala", rel_file, c, _visibility(c))
                n["signature"] = {"params": params, "returns": text(ret) if ret else None}
                if tps := declared_type_params(c):
                    res["type_params"][fid] = tps
                res["nodes"].append(n)
                parent["metrics"]["methods"] += 1
                scope_ids[c.start_byte] = fid
                if body is not None:
                    res["tapir"]["bodies"].append((fid, n["line"], text(body)))
                    starts.append(body.start_point[0] + 1)
                    def_names[len(starts) - 1] = ".".join(qual + [text(name_node)])
                    method_bodies.append((fid, text(body)))
                    if owner is not None:
                        anonymous(body, owner, qual, None)
            elif c.type == "val_definition":
                pat, val = c.child_by_field_name("pattern"), c.child_by_field_name("value")
                if pat is not None and val is not None and pat.type == "identifier":
                    hit = routes.tapir_val(qual, text(pat), text(val))
                    if hit:
                        res["tapir"]["vals"][hit[0]] = hit[1]
                        continue
                    holder = owner if owner is not None else file_node()
                    if owner is not None and _behaviour(c.child_by_field_name("type"), val, effects):
                        # `val run = ...`: a method of arity 0, so calls and routes can attach to it
                        typ = c.child_by_field_name("type")
                        fid = reg.claim(ids.method_id(owner["id"], text(pat), 0))
                        n = make_node(fid, "method", owner["id"], text(pat), "scala", rel_file, c, _visibility(c))
                        n["signature"] = {"params": [], "returns": text(typ) if typ else None}
                        if tps := declared_type_params(c):
                            res["type_params"][fid] = tps
                        res["nodes"].append(n)
                        owner["metrics"]["methods"] += 1
                        scope_ids[c.start_byte] = fid
                        method_bodies.append((fid, text(val)))
                        holder = n
                    # `val endpoint = Base.V1.x.get...`: the route belongs to the val, else the enclosing object
                    res["tapir"]["bodies"].append((holder["id"], c.start_point[0] + 1, text(val)))
                    starts.append(val.start_point[0] + 1)
                    val_bodies.append((len(res["tapir"]["bodies"]) - 1, text(pat), ".".join(qual + [text(pat)])))
                    if owner is not None:
                        anonymous(val, owner, qual, text(pat))

    def anonymous(node, owner: dict, qual: list[str], val_name: str | None) -> None:
        """`new T { def ... }`: a class `<owner>.<val>$impl` (or `<owner>.$impl<n>`) holding the defs."""
        for inst, body in _anonymous(node):
            if val_name is not None:
                seg = f"{val_name}$impl"
            else:
                unnamed[owner["id"]] = unnamed.get(owner["id"], 0) + 1
                seg = f"$impl{unnamed[owner['id']]}"
            cq = qual + [seg]
            cid = reg.claim(ids.qualified(mid, (pkg + "." if pkg != "_root_" else "") + ".".join(cq)))
            typ = next((c for c in inst.named_children if c.type != "template_body"), None)
            n = make_node(cid, "class", owner["id"], ("new " + text(typ))[:80] if typ else seg,
                          "scala", rel_file, inst)
            n["metrics"]["methods"] = 0
            res["nodes"].append(n)
            if supers := _type_names(typ):
                res["supers"].append((cid, supers))
            visit(body, n, cq)

    visit(root, None, [])
    # `val quote = endpoint.get...` served by `quote.zServerLogic(...)` in a def: that def handles the route
    for i, name, _ in val_bodies:
        users = [fid for fid, body in method_bodies if re.search(SERVER_LOGIC.format(re.escape(name)), body)]
        if len(users) == 1:
            _, line, body = res["tapir"]["bodies"][i]
            res["tapir"]["bodies"][i] = (users[0], line, body)

    for n in walk(root):
        if n.type == "import_declaration":
            for t, names, renames in _import_targets(text(n)):
                res["imports"].append({"target": t, "line": n.start_point[0] + 1, "relative": False})
                if names:
                    res["imports"][-1]["names"] = names
                if renames:
                    res["imports"][-1]["renames"] = renames
        elif n.type == "type_definition" and (alias := n.child_by_field_name("name")) is not None:
            res["aliases"].append(text(alias).strip("`"))
        elif n.type == "call_expression":
            fn = n.child_by_field_name("function")
            if fn is not None:
                res["calls"].append({"callee": callee_text(text(fn)), "in": enclosing_id(n, scope_ids),
                                     "line": fn.end_point[0] + 1,
                                     "args": _arg_count(n)})
        elif n.type in ("string", "interpolated_string_expression"):
            if n.type == "string" and n.parent is not None and n.parent.type == "interpolated_string_expression":
                continue
            body = _string_body(n)
            if body is not None:
                res["strings"].append({"text": body, "line": n.start_point[0] + 1,
                                       "in": enclosing_id(n, scope_ids)})
    res["tapir"]["root"] = any(i["target"].startswith("sttp.tapir") for i in res["imports"])
    # a file that interprets endpoints as requests describes calls it makes, not routes it serves
    res["tapir"]["client"] = any(i["target"].startswith("sttp.tapir.client") for i in res["imports"])
    res["tapir"]["named"] = {**def_names, **{i: q for i, _, q in val_bodies}}
    res["tapir"]["binds"] = [(fid, m.group(1), start + body.count("\n", 0, m.start()))
                             for (fid, _, body), start in zip(res["tapir"]["bodies"], starts)
                             for m in BINDS.finditer(body)]
    if any(i["target"].startswith(("sttp.client", "sttp.tapir.client")) for i in res["imports"]):
        res["tapir"]["mentions"] = sorted(set(DOTTED.findall(decode(src))))   # what a client file may call
    src_text = decode(src)
    for m in ENV.finditer(src_text):
        res["env_keys"].append({"key": m.group(1), "line": src_text.count("\n", 0, m.start()) + 1})
    return res
