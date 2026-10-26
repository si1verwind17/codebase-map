"""Python: modules are files, classes and functions become nodes; FastAPI routes."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from tree_sitter_language_pack import get_parser

from ... import ids
from .. import routes
from . import (arg_count, callee_text, declared_type_params, decode, enclosing_id, fields, make_node, new_result,
               text, walk)

PARSER = get_parser("python")
ENV = re.compile(r"os\.(?:getenv|environ\.get)\(\s*['\"]([A-Za-z0-9_]+)['\"]|os\.environ\[\s*['\"]([A-Za-z0-9_]+)['\"]\s*\]")
STRING_BODY = re.compile(r"^[a-zA-Z]*(\"\"\"|'''|\"|')(.*)\1$", re.S)


def dotted_names(module: dict, rel_file: str) -> tuple[str, str]:
    """(package dotted name, file dotted name) for a file in a module."""
    mod = module["path"]
    rel = PurePosixPath(rel_file).with_suffix("")
    if module["build"] == "python-package":
        base = PurePosixPath(mod)
        parts = [base.name] + list(rel.relative_to(base).parts)
        return ".".join(parts[:-1]), ".".join(parts)
    pkg = PurePosixPath(mod).name if mod != "." else "_root_"
    return pkg, f"{pkg}.{rel.name}"


def _visibility(name: str) -> str:
    dunder = name.startswith("__") and name.endswith("__")
    return "private" if name.startswith("_") and not dunder else "public"


def _params(fn, is_method: bool) -> list[dict]:
    out = []
    for p in fn.child_by_field_name("parameters").named_children:
        t = p.type
        if t == "identifier":
            name, typ = text(p), None
        elif t == "typed_parameter":
            name, typ = text(p.named_children[0]), p.child_by_field_name("type")
        elif t in ("default_parameter", "typed_default_parameter"):
            name, typ = text(p.child_by_field_name("name")), p.child_by_field_name("type")
        elif t == "list_splat_pattern":
            name, typ = "*" + text(p.named_children[0]), None
        elif t == "dictionary_splat_pattern":
            name, typ = "**" + text(p.named_children[0]), None
        else:
            continue
        out.append({"name": name, "type": text(typ) if typ is not None else None})
        if t in ("default_parameter", "typed_default_parameter"):
            out[-1]["optional"] = True
    if is_method and out and out[0]["name"] in ("self", "cls"):
        out = out[1:]
    return out


DAG_DECO = re.compile(r"@(?:[\w.]*\.)?dag\s*(?:\(|$)")
TASK_DECO = re.compile(r"@(?:[\w.]*\.)?task\b")
WORKFLOW_DECO = re.compile(r"@(?:[\w.]*\.)?workflow\s*(?:\(|$)")
REFERENCE_DECO = re.compile(r"@(?:[\w.]*\.)?reference_(task|workflow|launch_plan)\s*\(")
DAG_CALL = re.compile(r"(?:^|\.)DAG$")
LAUNCH_PLAN = re.compile(r"(?:^|\.)LaunchPlan\.(?:get_or_create|create)$")
SCHEDULE_KW = ("schedule", "schedule_interval", "timetable")
COMPOUND = ("if_statement", "elif_clause", "else_clause", "with_statement", "for_statement", "while_statement",
            "try_statement", "except_clause", "finally_clause", "block")


def _defs(block, skip_dag_blocks: bool = False):
    """(definition, decorators) for classes and functions in a block, looking through if/with/try
    statements (optionally not `with DAG(...)` ones) but not into other definitions."""
    out = []
    for c in block.named_children:
        if c.type == "decorated_definition":
            out.append((c.child_by_field_name("definition"), [d for d in c.named_children if d.type == "decorator"]))
        elif c.type in ("function_definition", "class_definition"):
            out.append((c, []))
        elif c.type in COMPOUND and not (skip_dag_blocks and c.type == "with_statement" and _dag_call(c)):
            out += _defs(c, skip_dag_blocks)
    return out


def _dag_bodies(root):
    """Bodies of the file's top-level @dag functions and `with DAG(...)` blocks."""
    out = []
    for c in root.named_children:
        if c.type == "decorated_definition" and any(
                DAG_DECO.match(text(d)) for d in c.named_children if d.type == "decorator"):
            out.append(c.child_by_field_name("definition").child_by_field_name("body"))
        elif c.type == "with_statement" and _dag_call(c):
            out.append(c.child_by_field_name("body"))
    return out


def _literal(node):
    """A string literal's value; any other expression as written (`None`, `timedelta(hours=1)`)."""
    if node is None:
        return None
    if node.type == "string" and not any(c.type == "interpolation" for c in node.named_children):
        m = STRING_BODY.match(text(node))
        if m:
            return m.group(2)
    return text(node)[:80]


def _args(call):
    """(positional argument nodes, {keyword: value node}) of a call node; ([], {}) for a bare name."""
    if call is None or call.type != "call":
        return [], {}
    pos, kw = [], {}
    for a in call.child_by_field_name("arguments").named_children:
        if a.type == "keyword_argument":
            kw[text(a.child_by_field_name("name"))] = a.child_by_field_name("value")
        elif a.type != "comment":
            pos.append(a)
    return pos, kw


def _deco_call(decorator):
    expr = decorator.named_children[0] if decorator.named_children else None
    return expr if expr is not None and expr.type == "call" else None


def _dag_call(with_stmt):
    for n in walk(with_stmt):
        if n.type == "block":
            break
        if n.type == "call" and DAG_CALL.search(text(n.child_by_field_name("function"))):
            return n
    return None


def _dag_fact(call, fn_name: str | None, node_id: str, at, body) -> dict:
    """An Airflow DAG: its id (`dag_id=`, the first positional string, else the function name),
    its schedule as written (None when not set) and its task names."""
    pos, kw = _args(call)
    dag_id = _literal(kw["dag_id"]) if "dag_id" in kw else (
        _literal(pos[0]) if pos and pos[0].type == "string" else fn_name)
    schedule = next((_literal(kw[k]) for k in SCHEDULE_KW if k in kw), None)
    tasks = [text(t.child_by_field_name("name")) for t, decos in _defs(body)
             if t.type == "function_definition" and any(TASK_DECO.match(text(d)) for d in decos)]
    for n in walk(body):
        if n.type == "keyword_argument" and text(n.child_by_field_name("name")) == "task_id":
            v = _literal(n.child_by_field_name("value"))
            if v and v not in tasks:
                tasks.append(v)
    return {"framework": "airflow", "id": dag_id, "schedule": schedule, "tasks": tasks,
            "node": node_id, "line": at.start_point[0] + 1}


def _dag_prefix(with_stmt, call, n: int) -> str:
    """Id prefix for tasks of a `with DAG(...)` block: the dag id when it is a plain string literal,
    else the `as <alias>` name, else `DAG<n>` (n counts the file's `with DAG` blocks in source order)."""
    pos, kw = _args(call)
    expr = kw.get("dag_id") if "dag_id" in kw else (pos[0] if pos else None)
    if expr is not None and expr.type == "string" and not any(c.type == "interpolation" for c in expr.named_children):
        m = STRING_BODY.match(text(expr))
        if m and m.group(2):
            return m.group(2)
    for item in walk(with_stmt):
        if item.type == "block":
            break
        if item.type == "as_pattern" and item.start_byte <= call.start_byte < item.end_byte:
            target = next((c for c in item.named_children if c.type == "as_pattern_target"), None)
            if target is not None and target.named_children and target.named_children[0].type == "identifier":
                return text(target.named_children[0])
    return f"DAG{n}"


def _launch_plans(root, workflows: list[dict]) -> None:
    """Flyte `LaunchPlan.get_or_create(wf, name=…, schedule=CronSchedule(…))` onto its workflow."""
    for n in walk(root):
        if n.type != "call" or not LAUNCH_PLAN.search(text(n.child_by_field_name("function"))):
            continue
        pos, kw = _args(n)
        wf = text(pos[0]) if pos and pos[0].type == "identifier" else (
            text(kw["workflow"]) if "workflow" in kw else None)
        sched = kw.get("schedule")
        if sched is not None and sched.type == "call":
            spos, skw = _args(sched)
            expr = skw.get("schedule") or skw.get("cron_expression") or (spos[0] if spos else None)
            sched_v = _literal(expr) if expr is not None and expr.type == "string" else text(sched)[:80]
        else:
            sched_v = _literal(sched)
        lp = {"name": _literal(kw["name"]) if "name" in kw else None, "schedule": sched_v,
              "line": n.start_point[0] + 1}
        entry = next((w for w in workflows if w["id"] == wf), None)
        if entry is None:
            entry = {"framework": "flyte", "id": wf, "node": None, "line": lp["line"], "launch_plans": []}
            workflows.append(entry)
        entry["launch_plans"].append(lp)


TYPE_FACTORIES = ("TypeVar", "NewType", "ParamSpec", "TypeVarTuple", "TypeAliasType")


def _type_aliases(root) -> list[str]:
    """Module-level type names that are no class: `type X = ...`, `X: TypeAlias = ...`, `X = Tuple[...]`,
    `X = A | B`, `X = other.Name`, `T = TypeVar("T")`."""
    out = []
    for stmt in root.named_children:
        n = stmt.named_children[0] if stmt.type == "expression_statement" and stmt.named_children else stmt
        if n.type == "type_alias_statement":
            left = n.child_by_field_name("left")
            name = re.match(r"\w+", text(left)) if left is not None else None
            if name:
                out.append(name.group(0))
            continue
        if n.type != "assignment":
            continue
        left, right, ann = (n.child_by_field_name(k) for k in ("left", "right", "type"))
        if left is None or left.type != "identifier" or right is None:
            continue
        if ann is not None and text(ann).rsplit(".", 1)[-1] == "TypeAlias" \
                or right.type in ("subscript", "attribute", "identifier") \
                or right.type == "binary_operator" and text(right.child_by_field_name("operator")) == "|" \
                or right.type == "call" and text(right.child_by_field_name("function")).rsplit(".", 1)[-1] \
                in TYPE_FACTORIES:
            out.append(text(left))
    return out


def parse(src: bytes, rel_file: str, module: dict, reg: ids.IdRegistry, st=None) -> dict:
    """`st` is unused: route patterns run in structure.build."""
    pkg, dotted = dotted_names(module, rel_file)
    tree = PARSER.parse(src)
    root = tree.root_node
    res = new_result(pkg, root.has_error)
    mid = module["id"]
    file_id = reg.claim(ids.qualified(mid, dotted))
    file_node = make_node(file_id, "file", ids.package_id(mid, pkg), PurePosixPath(rel_file).name,
                          "python", rel_file, root)
    res["nodes"].append(file_node)
    scope_ids: dict[int, str] = {}
    decorated: list[tuple] = []  # (handler id, decorator texts, line, nested handler name or None)
    res.update(bases=[], dags=[], workflows=[], reference_tasks=[])
    # Airflow tasks nested in a @dag function (or defined in a `with DAG(...)` block) are methods of the
    # file; a name that is also a plain top-level function, or a task of another DAG in the file, is
    # qualified with its DAG: `<dag function>.<task>` / `<dag_id>.<task>`
    top_names = {text(t.child_by_field_name("name")) for t, _ in _defs(root, skip_dag_blocks=True)
                 if t.type == "function_definition"}
    nested_seen: dict[str, int] = {}
    for body in _dag_bodies(root):
        for name in {text(i.child_by_field_name("name")) for i, _ in _defs(body)}:
            nested_seen[name] = nested_seen.get(name, 0) + 1
    qualify = top_names | {k for k, v in nested_seen.items() if v > 1}
    dag_blocks = [0]   # `with DAG(...)` blocks seen so far, for the `DAG<n>` id prefix

    def add_function(target, decos, owner_id: str, owner_node: dict, label: str | None = None) -> str:
        name = text(target.child_by_field_name("name"))
        params = _params(target, owner_node["kind"] == "class")
        fid = reg.claim(ids.method_id(owner_id, label or name, len(params)))
        ret = target.child_by_field_name("return_type")
        n = make_node(fid, "method", owner_id, name, "python", rel_file, target, _visibility(name))
        n["signature"] = {"params": params, "returns": text(ret) if ret else None}
        if tps := declared_type_params(target):
            res["type_params"][fid] = tps
        res["nodes"].append(n)
        owner_node["metrics"]["methods"] = owner_node["metrics"].get("methods", 0) + 1
        scope_ids[target.start_byte] = fid
        if decos:
            decorated.append((fid, [text(d) for d in decos], n["line"], None))
        return fid

    def visit(container, owner_id: str, owner_qual: str, owner_node: dict, dag_prefix: str | None = None) -> None:
        for c in container.named_children:
            target, decos = c, []
            if c.type == "decorated_definition":
                decos = [d for d in c.named_children if d.type == "decorator"]
                target = c.child_by_field_name("definition")
            if target.type == "with_statement" and owner_node["kind"] == "file" and (call := _dag_call(target)):
                fact = _dag_fact(call, None, file_id, target, target.child_by_field_name("body"))
                dag_blocks[0] += 1
                visit(target.child_by_field_name("body"), owner_id, owner_qual, owner_node,
                      _dag_prefix(target, call, dag_blocks[0]))
                res["dags"].append(fact)
                continue
            name_node = target.child_by_field_name("name")
            if name_node is None:
                continue
            name = text(name_node)
            if target.type == "class_definition":
                qual = f"{owner_qual}.{name}"
                cid = reg.claim(ids.qualified(mid, qual))
                n = make_node(cid, "class", owner_id, name, "python", rel_file, target, _visibility(name))
                n["metrics"]["methods"] = 0
                if found_fields := fields.python(target):
                    n["fields"] = found_fields
                res["nodes"].append(n)
                sup = target.child_by_field_name("superclasses")
                if sup is not None:
                    res["bases"].append((cid, [text(b) for b in sup.named_children
                                                if b.type in ("identifier", "attribute")]))
                    if kws := [text(b) for b in sup.named_children if b.type == "keyword_argument"]:
                        res.setdefault("class_keywords", {})[cid] = kws   # `class User(Base, table=True)`
                visit(target.child_by_field_name("body"), cid, qual, n)
            elif target.type == "function_definition":
                fid = add_function(target, decos, owner_id, owner_node,
                                   f"{dag_prefix}.{name}" if dag_prefix and name in qualify else None)
                deco = next((d for d in decos if DAG_DECO.match(text(d))), None)
                if deco is not None and owner_node["kind"] == "file":
                    body = target.child_by_field_name("body")
                    for inner, inner_decos in _defs(body):
                        if inner.type == "function_definition":
                            iname = text(inner.child_by_field_name("name"))
                            add_function(inner, inner_decos, owner_id, owner_node,
                                         f"{name}.{iname}" if iname in qualify else None)
                    res["dags"].append(_dag_fact(_deco_call(deco), name, fid, deco, body))
                for d in decos:
                    dt = text(d)
                    if WORKFLOW_DECO.match(dt):
                        res["workflows"].append({"framework": "flyte", "id": name, "node": fid,
                                                 "line": d.start_point[0] + 1, "launch_plans": []})
                    elif m := REFERENCE_DECO.match(dt):
                        _, kw = _args(_deco_call(d))
                        res["reference_tasks"].append({
                            "kind": m.group(1), **{k: _literal(kw[k]) if k in kw else None
                                                   for k in ("project", "domain", "name")},
                            "node": fid, "line": d.start_point[0] + 1})

    visit(root, file_id, dotted, file_node)
    _launch_plans(root, res["workflows"])
    # functions nested in a function are not nodes: a route on one credits the enclosing function, and structure
    # makes the nested function a node (res["nested"])
    for n in walk(root):
        if n.type == "function_definition" and n.start_byte not in scope_ids \
                and (outer := enclosing_id(n, scope_ids)) is not None:
            deco = n.parent if n.parent is not None and n.parent.type == "decorated_definition" else n
            res["nested"].append({"name": text(n.child_by_field_name("name")), "start": deco.start_point[0] + 1,
                                  "line": n.start_point[0] + 1, "end": n.end_point[0] + 1, "in": outer,
                                  "params": _params(n, False)})
        if n.type == "decorated_definition":
            target = n.child_by_field_name("definition")
            if target.type == "function_definition" and target.start_byte not in scope_ids:
                decos = [text(d) for d in n.named_children if d.type == "decorator"]
                decorated.append((enclosing_id(target, scope_ids) or file_id, decos, target.start_point[0] + 1,
                                  text(target.child_by_field_name("name"))))

    src_text = decode(src)
    prefixes = routes.fastapi_prefixes(src_text)
    res["includes"] = routes.fastapi_includes(src_text)
    res["routers"] = prefixes
    for fid, decos, line, nested in decorated:
        for d in decos:
            hit = routes.fastapi_decorator(d)
            if hit and hit[0] in prefixes:
                obj, method, path = hit
                route = {"method": method, "path": prefixes[obj] + path, "handler": fid,
                         "line": line, "framework": "fastapi", "router": obj}
                if nested:
                    route["nested_handler"] = nested
                res["routes"].append(route)

    res["aliases"] = _type_aliases(root)
    for n in walk(root):
        if n.type == "import_statement":
            for name in n.named_children:
                target = name.child_by_field_name("name") if name.type == "aliased_import" else name
                res["imports"].append({"target": text(target), "line": n.start_point[0] + 1, "relative": False})
                if name.type == "aliased_import" and (alias := name.child_by_field_name("alias")) is not None:
                    res["imports"][-1]["as"] = text(alias)
        elif n.type == "import_from_statement":
            target = text(n.child_by_field_name("module_name"))
            names = [text(x.child_by_field_name("name") if x.type == "aliased_import" else x)
                     for x in n.children_by_field_name("name")]
            res["imports"].append({"target": target, "line": n.start_point[0] + 1,
                                   "relative": target.startswith("."), "names": names})
            renamed = {text(a): text(x.child_by_field_name("name")) for x in n.children_by_field_name("name")
                       if x.type == "aliased_import" and (a := x.child_by_field_name("alias")) is not None}
            if renamed:
                res["imports"][-1]["renames"] = renamed
        elif n.type == "call":
            fn = n.child_by_field_name("function")
            res["calls"].append({"callee": callee_text(text(fn)), "in": enclosing_id(n, scope_ids),
                                 "line": fn.end_point[0] + 1,
                                 "args": arg_count(n, ("list_splat", "dictionary_splat"))})
        elif n.type == "concatenated_string" or (
                n.type == "string" and (n.parent is None or n.parent.type != "concatenated_string")):
            parts = n.named_children if n.type == "concatenated_string" else [n]
            bodies = [m.group(2) for p in parts if (m := STRING_BODY.match(text(p)))]
            if bodies:
                res["strings"].append({"text": "".join(bodies), "line": n.start_point[0] + 1,
                                       "in": enclosing_id(n, scope_ids)})
    for m in ENV.finditer(src_text):
        res["env_keys"].append({"key": m.group(1) or m.group(2), "line": src_text.count("\n", 0, m.start()) + 1})
    return res
