"""One tree walker for every language in adapters/langs.py: classes, functions, imports, calls, strings,
annotations. Scala and Python keep their own adapters."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Callable

from tree_sitter_language_pack import get_parser

from .. import ids
from . import callee_text, count_args, declared_type_params, decode, fields, make_node, new_result, text, walk
from .langs import LangSpec

QUOTED = re.compile(r'^([@$A-Za-z]{0,3}#*)("""|"|\'|`)(.*)\2(#*)$', re.S)     # Rust r#"..."#
TURBOFISH = re.compile(r"::(?=\(|$)")      # `parse::<u32>()` once its type arguments are cut
Import = tuple       # target, names, relative, the node giving the line[, the local name of the whole import]
_PARSERS: dict[str, object] = {}


def child(node, key: str):
    """The child a table key names (langs.py): a field, else a named child of that type; "" = first identifier."""
    if not key:
        return next((c for c in node.named_children if c.type.endswith("identifier")), None)
    return node.child_by_field_name(key) or next((c for c in node.named_children if c.type == key), None)


def _children(node, key: str) -> list:
    """Every child a key names (a field may repeat; else the named children of that type)."""
    return node.children_by_field_name(key) or [c for c in node.named_children if c.type == key]


def _first(node, keys: tuple[str, ...]):
    return next((c for c in (child(node, k) for k in keys) if c is not None), None)


def _path(node, keys: tuple[str, ...]):
    for k in keys:
        if node is None:
            return None
        node = child(node, k)
    return node


def _split_last(name: str, sep: str, node) -> Import:
    """`a.b.C` -> (a.b, [C]); a name without a separator is the target alone."""
    head, _, last = name.rpartition(sep)
    return (head, [last], False, node) if head else (name, [], False, node)


def _qualified_name(node, spec: LangSpec) -> list[Import]:
    """`import a.b.C` -> (a.b, [C]); `import a.b.*` -> (a.b, []); a static import alike (the class, [member])."""
    parts = [c for c in node.named_children if c.type not in spec.comments]
    if not parts:
        return []
    name = re.sub(r"\s+", "", text(parts[0]))
    if any(c.type in spec.wildcards for c in parts):
        return [(name, [], False, node)]
    return [_split_last(name, ".", node)]


def _whole_name(node, spec: LangSpec) -> list[Import]:
    """C# `using A.B;`, `using X = A.B;`, `using static A.B;` -> (A.B, []): the last name in the directive."""
    parts = [c for c in node.named_children if c.type not in spec.comments]
    return [(re.sub(r"\s+", "", text(parts[-1])), [], False, node)] if parts else []


def _unquote(node) -> str | None:
    m = QUOTED.match(text(node))
    return m.group(3) if m else None


def _es_module(node, spec: LangSpec) -> list[Import]:
    """`import {a, b as c} from "x"` -> (x, [a, b]); `export {y} from "./y"`, `import z = require("z")` alike;
    an export without `from` is no import."""
    source = node.child_by_field_name("source") or next(
        (s for c in node.named_children if (s := c.child_by_field_name("source")) is not None), None)
    target = _unquote(source) if source is not None else None
    if target is None:
        return []
    names = [text(n) for s in walk(node) if s.type in ("import_specifier", "export_specifier")
             and (n := s.child_by_field_name("name")) is not None]
    local = next((text(i) for s in walk(node) if s.type == "namespace_import"
                  for i in s.named_children if i.type == "identifier"), None)
    return [(target, names, target.startswith("."), node, local)]


def _one_string(args, spec: LangSpec, types: tuple[str, ...]) -> str | None:
    """The contents of a lone string argument without interpolations."""
    named = [a for a in args.named_children if a.type not in spec.comments] if args is not None else []
    if len(named) != 1 or named[0].type not in types \
            or any(c.type in spec.interpolations for c in named[0].named_children):
        return None
    return _unquote(named[0])


def _require(node, spec: LangSpec) -> list[Import]:
    """`require("x")`, `import("./y")` with one string argument; any other call is no import."""
    fn, args = node.child_by_field_name("function"), node.child_by_field_name("arguments")
    if fn is None or fn.type not in ("identifier", "import") or text(fn) not in ("require", "import") or args is None:
        return []
    target = _one_string(args, spec, ("string",))
    return [] if target is None else [(target, [], target.startswith("."), node)]


def _ruby_require(node, spec: LangSpec) -> list[Import]:
    """`require "x"`, `require_relative "../y"` (relative); any other call is no import."""
    method = node.child_by_field_name("method")
    if node.child_by_field_name("receiver") is not None or method is None \
            or text(method) not in ("require", "require_relative"):
        return []
    target = _one_string(node.child_by_field_name("arguments"), spec, ("string",))
    if target is None:
        return []
    return [(target, [], text(method) == "require_relative" or target.startswith("."), node)]


def _go_import(node, spec: LangSpec) -> list[Import]:
    """`import ( "fmt"; log "github.com/x/logrus" )` -> one import per path, on its own line."""
    out = []
    for s in walk(node):
        if s.type == "import_spec" and (path := s.child_by_field_name("path")) is not None:
            if (target := _unquote(path)) is not None:
                name = s.child_by_field_name("name")
                local = text(name) if name is not None and name.type == "package_identifier" else None
                out.append((target, [], target.startswith("."), s, local))
    return out


RUST_RELATIVE = ("crate", "self", "super")


def _rust_paths(n, prefix: str):
    """(path, node) for each name a `use` tree imports: `a::b::{c, d as e}` -> a::b::c, a::b::d."""
    def join(p: str) -> str:
        return f"{prefix}::{p}" if prefix and p else prefix or p
    if n.type == "scoped_use_list":
        path = n.child_by_field_name("path")
        inner = join(re.sub(r"\s+", "", text(path)) if path is not None else "")
        lst = n.child_by_field_name("list")
        for c in (lst.named_children if lst is not None else []):
            yield from _rust_paths(c, inner)
    elif n.type == "use_list":
        for c in n.named_children:
            yield from _rust_paths(c, prefix)
    elif n.type == "use_as_clause":
        if (path := n.child_by_field_name("path")) is not None:
            yield from _rust_paths(path, prefix)
    elif n.type == "use_wildcard":
        yield join(re.sub(r"\s+", "", text(n)).removesuffix("::*").removesuffix("*")), n
    elif n.type == "self":
        yield prefix, n
    elif n.is_named:
        yield join(re.sub(r"\s+", "", text(n))), n


def _rust_use(node, spec: LangSpec) -> list[Import]:
    """`use a::b::{c, d}` -> a::b::c, a::b::d; `crate::`, `self::`, `super::` paths are relative."""
    arg = node.child_by_field_name("argument")
    if arg is None:
        return []
    return [(p, [], p.split("::", 1)[0] in RUST_RELATIVE, line) for p, line in _rust_paths(arg, "") if p]


def _rust_mod(node, spec: LangSpec) -> list[Import]:
    """`mod db;` names a file of the crate (relative); a `mod x { ... }` with a body is a class."""
    name = node.child_by_field_name("name")
    if node.child_by_field_name("body") is not None or name is None:
        return []
    return [(text(name), [], True, node)]


def _php_use(node, spec: LangSpec) -> list[Import]:
    """`use A\\B\\C;` -> (A\\B, [C]); `use D\\{E, F as G};` -> (D, [E, F]); a leading `\\` is dropped."""
    def name_of(clause) -> str:
        n = next((c for c in clause.named_children if c.type in ("qualified_name", "name", "namespace_name")
                  and clause.field_name_for_child(clause.children.index(c)) != "alias"), None)
        return re.sub(r"\s+", "", text(n)).lstrip("\\") if n is not None else ""
    group = node.child_by_field_name("body")
    if group is not None:
        prefix = next((c for c in node.named_children if c.type == "namespace_name"), None)
        names = [name_of(c) for c in group.named_children if c.type == "namespace_use_clause"]
        head = text(prefix).lstrip("\\") if prefix is not None else ""
        return [(head, [n for n in names if n], False, node)] if head else []
    return [_split_last(n, "\\", node) for c in node.named_children
            if c.type == "namespace_use_clause" and (n := name_of(c))]


IMPORT_READERS: dict[str, Callable[[object, LangSpec], list[Import]]] = {
    "qualified-name": _qualified_name,
    "whole-name": _whole_name,
    "es-module": _es_module,
    "require": _require,
    "ruby-require": _ruby_require,
    "go-import": _go_import,
    "rust-use": _rust_use,
    "rust-mod": _rust_mod,
    "php-use": _php_use,
}


def _parser(grammar: str):
    if grammar not in _PARSERS:
        _PARSERS[grammar] = get_parser(grammar)
    return _PARSERS[grammar]


def _folder(rel_file: str, module: dict) -> str:
    folder = PurePosixPath(rel_file).parent
    if module["path"] != ".":
        folder = folder.relative_to(module["path"]) if folder.is_relative_to(module["path"]) else folder
    return "_root_" if str(folder) == "." else str(folder)


def _package(root, spec: LangSpec, rel_file: str, module: dict) -> tuple[str, object]:
    """The package name, and the top-level node naming it (None for a folder package)."""
    kinds = (spec.package,) if isinstance(spec.package, str) else spec.package
    for c in root.named_children:
        if c.type in kinds:
            name = c.child_by_field_name("name") or next(
                (x for x in c.named_children if x.type not in spec.annotations and x.type not in spec.comments), None)
            if name is not None:
                return re.sub(r"\s+", "", text(name)).replace("::", "."), c     # Ruby `module A::B`
    return (_folder(rel_file, module) if "dir" in kinds else "_root_"), None


def _declared(root, spec: LangSpec, rel_file: str) -> str | None:
    """A declared package name other than the folder's last segment (Go `package x` in folder `y`)."""
    for c in root.named_children:
        if c.type in spec.declared_package:
            name = next((x for x in c.named_children if x.type not in spec.comments), None)
            return text(name) if name is not None and text(name) != PurePosixPath(rel_file).parent.name else None
    return None


def _type_params(node, spec: LangSpec) -> set[str]:
    """Names of the type parameters a node declares (Rust `impl<T, U>`)."""
    plist = child(node, spec.attach_params) if spec.attach_params else None
    return {text(n) for c in (plist.named_children if plist is not None else [])
            if (n := c.child_by_field_name("name")) is not None}


def _annotations(decl, name_node, spec: LangSpec) -> list:
    """Annotations before the declaration's name (in it or one level down, e.g. Java `modifiers`), and the
    annotation siblings just before it (TypeScript decorators)."""
    before = []
    sib = decl.prev_named_sibling
    while sib is not None and (sib.type in spec.annotations or sib.type in spec.comments):
        if sib.type in spec.annotations:
            before.insert(0, sib)
        sib = sib.prev_named_sibling
    inside = []
    for c in decl.named_children:
        if c.start_byte >= name_node.start_byte:
            break
        inside += [c] if c.type in spec.annotations else [g for g in c.named_children if g.type in spec.annotations]
    return before + inside


def _container(decl, spec: LangSpec):
    """The class-like node a declaration is a member of (a class, or a node holding attached methods)."""
    p = decl.parent
    while p is not None:
        if p.type in spec.classes or (p.type in spec.attach and p.type not in spec.functions):
            return p
        p = p.parent
    return None


def _opens(container, spec: LangSpec) -> bool:
    """Members of this container are public whatever is written (`public_in`)."""
    for rule in spec.public_in:
        kind, _, key = rule.partition("/")
        if container.type == kind and (not key or container.child_by_field_name(key) is not None):
            return True
    return False


def _section(decl, spec: LangSpec) -> str | None:
    """The visibility set by the last bare section word before the declaration (Ruby `private`)."""
    sib = decl.prev_named_sibling
    while sib is not None:
        if not sib.named_children and (word := text(sib).strip()) in spec.sections:
            return spec.sections[word]
        sib = sib.prev_named_sibling
    return None


def _visibility(src: bytes, decl, name_node, annots: list, spec: LangSpec) -> str:
    """Public inside an interface or trait; else private when the modifier text and name (the declaration up to
    the end of its name, annotations blanked) say so, when a member names no access level where that means
    private (C#), or after a section word (Ruby)."""
    container = _container(decl, spec)
    if container is not None and _opens(container, spec):
        return "public"
    if spec.upper_exported and not _name(name_node)[:1].isupper():
        return "private"
    start = decl.start_byte
    head = bytearray(src[start:name_node.end_byte])
    for a in annots:
        if a.start_byte >= start and a.end_byte <= name_node.start_byte:
            head[a.start_byte - start:a.end_byte - start] = b" " * (a.end_byte - a.start_byte)
    words = decode(bytes(head))
    if re.search(spec.private, words):
        return "private"
    if container is not None and spec.member_access and not re.search(spec.member_access, words):
        return "private"
    return (_section(decl, spec) if spec.sections else None) or "public"


def _without(src: bytes, node, skip: tuple[str, ...], start: int | None = None, end: int | None = None) -> str:
    """Source of node (or of its bytes start..end) with the descendants of the skipped types cut out
    (`X<T>` -> `X`)."""
    start = node.start_byte if start is None else start
    end = node.end_byte if end is None else end
    cuts, stack = [], [node]
    while stack:
        n = stack.pop()
        if n.start_byte >= end or n.end_byte <= start:
            continue
        if n.type in skip and n is not node:
            cuts.append((max(n.start_byte, start), min(n.end_byte, end)))
            continue
        stack.extend(n.named_children)
    out, pos = [], start
    for a, b in sorted(cuts):
        out.append(src[pos:a])
        pos = max(pos, b)
    out.append(src[pos:end])
    return decode(b"".join(out))


def _supers(src: bytes, cls, spec: LangSpec) -> list[str]:
    """Type names a class extends or implements, as written, without type arguments."""
    out = []
    for key in spec.supers:
        stack = list(reversed(_children(cls, key)))
        while stack:
            n = stack.pop()
            if n.type in spec.not_supers or n.type in spec.type_args:
                continue
            if n.type in spec.type_names:
                out.append(re.sub(r"\s+", "", _without(src, n, spec.type_args)))
                continue
            stack.extend(reversed(n.named_children))
    return out


def _is_class(node, spec: LangSpec) -> bool:
    """A class node type, and when `class_when` names it, its key child is one of the listed types."""
    if node.type not in spec.classes:
        return False
    if node.type not in spec.class_when:
        return True
    key, kinds = spec.class_when[node.type]
    value = child(node, key)
    return value is not None and value.type in kinds


def _last_name(node):
    """`exports.handler` -> `handler`: the last name in a bound target."""
    while not node.type.endswith("identifier") and node.named_children:
        node = node.named_children[-1]
    return node


def _name(node) -> str:
    return text(node).strip("`").replace("::", ".")      # Kotlin `place order`; Ruby `class A::B`


def _type(node) -> str | None:
    return (text(node).lstrip(":").strip() or None) if node is not None else None


NOT_NAMED_BY = ("type", "value", "default_value", "right")


def _param_name(p, spec: LangSpec):
    """(name node or None, variadic): a name node is itself; else its name or pattern, or the key or left side
    of a destructuring or default (`{b: c}` -> b, `{a} = foo` -> a); else the first name inside it. Types and
    default values never name it."""
    variadic, stack = False, [p]
    while stack:
        n = stack.pop()
        variadic = variadic or n.type in spec.variadic
        if n.type in spec.names:
            return n, variadic
        side = next((c for k in ("name", "pattern", "left", "key") if (c := n.child_by_field_name(k)) is not None),
                    None)
        if side is not None:
            stack.append(side)
            continue
        stack.extend(c for i, c in reversed(list(enumerate(n.children)))
                     if c.is_named and c.type != "modifiers" and c.type not in spec.types
                     and n.field_name_for_child(i) not in NOT_NAMED_BY)
    return None, variadic


def _param(p, spec: LangSpec, marked: bool) -> list[dict]:
    """A parameter node's parameters (Go `a, b int` is two); the type only from a `type` field or a type node."""
    if p.type in spec.names:
        named, typ = [(p, False)], None
    else:
        typ = p.child_by_field_name("type") or next((c for c in p.named_children if c.type in spec.types), None)
        several = p.children_by_field_name("name")
        named = [(n, False) for n in several] if len(several) > 1 else [_param_name(p, spec)]
    out = []
    for name, variadic in named:
        label = text(name) if name is not None else "_"
        star = marked or variadic or p.type in spec.variadic
        out.append({"name": "*" + label if star else label, "type": _type(typ)})
    return out


def _params(fn, spec: LangSpec) -> list[dict]:
    plist = _first(fn, spec.params[0])
    if plist is None:
        return []
    if plist.type in spec.params[1]:
        return _param(plist, spec, False)          # a lone parameter (JS `x => x`)
    out, marked, typ = [], False, None
    for i, p in enumerate(plist.children):
        field = plist.field_name_for_child(i)
        if field == "type":
            typ = p
        elif field == "name":     # C# `params int[] rest` sits in the list itself
            out.append({"name": ("*" if marked else "") + text(p), "type": _type(typ)})
            marked = False
        elif p.type in spec.params[1]:
            out += _param(p, spec, marked)
            marked = False
        elif p.type not in spec.comments and any(d.type in spec.variadic for d in walk(p)):
            marked = True         # Kotlin `vararg`, C# `params`: a marker before the parameter
    return out


def _string(src: bytes, n, spec: LangSpec) -> str | None:
    """Contents between the delimiters, interpolations as {..}; None when the delimiters are not found.
    Delimiters are the first/last anonymous children, else read off the text (`@"..."`, Kotlin, Rust `r#"..."#`);
    a bare string (heredoc body) has none."""
    kids = n.children
    if n.type in spec.bare_strings:
        start, end = n.start_byte, n.end_byte
    elif len(kids) >= 2 and not kids[0].is_named and not kids[-1].is_named:
        start, end = kids[0].end_byte, kids[-1].start_byte
    else:
        m = QUOTED.match(text(n))
        if m is None:
            return None
        start = n.start_byte + len((m.group(1) + m.group(2)).encode())
        end = n.end_byte - len((m.group(2) + m.group(4)).encode())
    out, pos = [], start
    for c in kids:
        if c.end_byte <= start or c.start_byte >= end:
            continue
        if c.type in spec.interpolations or c.type in spec.interpolation_marks:
            out.append(decode(src[pos:c.start_byte]))
            pos = c.end_byte
        if c.type in spec.interpolations:
            inner = [x for x in c.named_children if x.type not in spec.interpolation_marks]
            body = decode(src[inner[0].start_byte:inner[-1].end_byte]) if inner else text(c)
            out.append("{" + body.strip() + "}")
    out.append(decode(src[pos:end]))
    return "".join(out)


def _arg_count(args, spec: LangSpec) -> int | None:
    """count_args, with a splat also seen one level down (Kotlin `value_argument > spread_expression`)."""
    if args is not None and any(g.type in spec.splats for a in args.named_children for g in a.named_children):
        return None
    return count_args(args, spec.splats, spec.comments)


def parse(src: bytes, rel_file: str, module: dict, reg: ids.IdRegistry, st=None, *, spec: LangSpec) -> dict:
    """`st` is unused: route patterns run in structure.build on the method spans this returns."""
    root = _parser(spec.grammar).parse(src).root_node
    pkg, pkg_node = _package(root, spec, rel_file, module)
    res = new_result(pkg, root.has_error)
    res["annotations"], res["attached"] = [], []
    if spec.declared_package and (declared := _declared(root, spec, rel_file)) is not None:
        res["package_declared"] = declared
    mid = module["id"]
    pkg_id = ids.package_id(mid, pkg)
    prefix = "" if pkg == "_root_" else pkg + "."
    file_holder: list[dict] = []
    classes: dict[str, dict] = {}       # class id -> node, declared in this file
    joined: dict[str, dict] = {}        # class id -> class node for a type methods attach to (`attach`)
    supers: dict[str, list[str]] = {}
    selves: dict[str, str] = {}         # method id -> the name its own object goes by (`self_name`)

    def file_node() -> dict:
        """Created on the first top-level function, as Scala's: a file of classes only has none."""
        if not file_holder:
            name = PurePosixPath(rel_file).name
            n = make_node(reg.claim(f"{pkg_id}{name}"), "file", pkg_id, name, spec.lang, rel_file, root)
            n["metrics"]["methods"] = 0
            res["nodes"].append(n)
            file_holder.append(n)
        return file_holder[0]

    def declare(decl, name_node, nid: str, kind: str, parent: str) -> dict:
        annots = _annotations(decl, name_node, spec)
        n = make_node(nid, kind, parent, _name(name_node), spec.lang, rel_file, decl,
                      _visibility(src, decl, name_node, annots, spec))
        if annots and annots[0].start_byte < decl.start_byte:     # decorators before it open its span
            n["line"] = annots[0].start_point[0] + 1
            n["metrics"]["loc"] = decl.end_point[0] - annots[0].start_point[0] + 1
        res["nodes"].append(n)
        res["annotations"] += [{"node": nid, "text": text(a), "line": a.start_point[0] + 1} for a in annots]
        return n

    def function(decl, fn, name_node, owner) -> str:
        parent = owner if owner is not None else file_node()
        params = _params(fn, spec)
        fid = reg.claim(ids.method_id(parent["id"], _name(name_node), len(params)))
        node = declare(decl, name_node, fid, "method", parent["id"])
        node["signature"] = {"params": params, "returns": _type(_first(fn, spec.returns))}
        if tps := declared_type_params(fn):
            res["type_params"][fid] = tps
        parent["metrics"]["methods"] += 1
        if spec.self_name and (own := _path(fn, spec.self_name)) is not None:
            selves[fid] = text(own)
        return fid

    def bound(n):
        """`const f = () => ...`: (name node, function value) when a name is bound to a function."""
        name_key, value_key, kinds = spec.bindings[n.type]
        value, name_node = child(n, value_key), child(n, name_key)
        if value is None or value.type not in kinds or name_node is None:
            return None
        return _last_name(name_node), value

    def named_function(n):
        """(name node, function) of a function declaration or a name bound to a function value."""
        if n.type in spec.functions and (name_node := child(n, spec.functions[n.type])) is not None:
            return name_node, n
        return bound(n) if n.type in spec.bindings else None

    def attached_to(n, qual: tuple, owner) -> tuple[dict, tuple] | None:
        """The class node of the type a Go receiver or Rust `impl` names (the one declared in this file, else a
        class node kept for the structure pass), and its qualified names."""
        tnode = _path(n, spec.attach[n.type])
        while tnode is not None and tnode.type in spec.attach_unwrap:
            tnode = tnode.child_by_field_name("type")
        if tnode is not None and spec.attach_types and (tnode.type not in spec.attach_types
                                                        or text(tnode) in _type_params(n, spec)):
            return None           # a blanket impl, a tuple: its functions stay on the file node
        m = re.search(r"(\w+)\W*$", _without(src, tnode, spec.type_args)) if tnode is not None else None
        if m is None:
            return None
        cq = qual + (m.group(1),)
        cid = ids.qualified(mid, file_prefix + ".".join(cq))
        if cid in classes:
            return classes[cid], cq
        if cid not in joined:
            joined[cid] = make_node(cid, "class", owner["id"] if owner else pkg_id, m.group(1), spec.lang,
                                    rel_file, n)
            joined[cid]["metrics"]["methods"] = 0
        return joined[cid], cq

    stem = PurePosixPath(rel_file).stem
    file_prefix = prefix + stem + "." if spec.file_qualified else prefix
    # iterative, so a deeply nested expression cannot hit the recursion limit; items are
    # (node, owner class node, qualified class names, enclosing method id, inside a string, inside an annotation)
    todo = [(root, None, (), None, False, False)]
    while todo:
        n, owner, qual, scope, in_str, in_annot = todo.pop()
        t, nxt = n.type, (owner, qual, scope, in_str, in_annot)
        if spec.test_only and (t in spec.classes or t in spec.functions or t in spec.imports or t in spec.attach) \
                and _test_only(n, spec):
            continue
        if t in spec.aliases and not _is_class(n, spec) and (alias := child(n, spec.aliases[t])) is not None:
            res["aliases"].append(_name(alias))
        if t in spec.imports and (found := IMPORT_READERS[spec.imports[t]](n, spec)):
            for target, names, relative, at, *local in found:
                res["imports"].append({"target": target, "line": at.start_point[0] + 1,
                                       "relative": relative, "names": names})
                if local and local[0]:
                    res["imports"][-1]["as"] = local[0]
            continue
        if pkg_node is not None and n == pkg_node:
            pass                  # Ruby's outermost module names the package: walked, not a class
        elif scope is None and _is_class(n, spec) and (name_node := child(n, spec.classes[t])) is not None:
            cq = qual + (_name(name_node),)
            cid = reg.claim(ids.qualified(mid, file_prefix + ".".join(cq)))
            node = classes[cid] = declare(n, name_node, cid, "class", owner["id"] if owner else pkg_id)
            node["metrics"]["methods"] = 0
            if found_fields := fields.read(spec.lang, n):
                node["fields"] = found_fields
            if found_supers := _supers(src, n, spec):
                supers.setdefault(cid, []).extend(found_supers)
            nxt = (node, cq, None, in_str, in_annot)
        elif scope is None and t in spec.attach and t not in spec.functions \
                and (hit := attached_to(n, qual, owner)) is not None:
            if found_supers := _supers(src, n, spec):          # Rust `impl Trait for T`
                supers.setdefault(hit[0]["id"], []).extend(found_supers)
            nxt = (hit[0], hit[1], None, in_str, in_annot)
        elif scope is None and t in spec.functions and (name_node := child(n, spec.functions[t])) is not None:
            hit = attached_to(n, qual, owner) if t in spec.attach else None
            nxt = (owner, qual, function(n, n, name_node, hit[0] if hit else owner), in_str, in_annot)
        elif scope is None and t in spec.bindings and (hit := bound(n)) is not None:
            nxt = (owner, qual, function(n, hit[1], hit[0], owner), in_str, in_annot)
        elif scope is not None and (hit := named_function(n)) is not None:
            res["nested"].append(_nested(n, hit[1], _name(hit[0]), scope, _params(hit[1], spec)))
        elif t in spec.annotations:
            nxt = (owner, qual, scope, in_str, True)
        elif t in spec.calls and not in_annot:
            keys, args = spec.calls[t]
            parts = [c for c in (child(n, k) for k in keys) if c is not None]
            if parts:
                callee = TURBOFISH.sub("", _without(src, n, spec.type_args, parts[0].start_byte, parts[-1].end_byte))
                res["calls"].append({"callee": callee_text(callee), "in": scope, "line": parts[-1].end_point[0] + 1,
                                     "args": _arg_count(_path(n, args), spec)})
                if scope in selves and re.match(rf"{re.escape(selves[scope])}\b", callee):
                    res["calls"][-1]["self"] = selves[scope]       # a call on the method's own object
        elif t in spec.strings and not in_str:
            body = _string(src, n, spec)
            if body is not None:
                res["strings"].append({"text": body, "line": n.start_point[0] + 1, "in": scope})
            nxt = (owner, qual, scope, True, in_annot)
        todo.extend((c, *nxt) for c in reversed(n.named_children))

    for cid, node in joined.items():
        if cid in classes:        # declared after the methods that attach to it
            classes[cid]["metrics"]["methods"] += node["metrics"]["methods"]
        else:
            res["attached"].append(node)
    res["supers"] = list(supers.items())
    src_text = decode(src)
    for m in re.finditer(spec.env, src_text):
        key = next(g for g in m.groups() if g)
        res["env_keys"].append({"key": key, "line": src_text.count("\n", 0, m.start()) + 1})
    return res


def _test_only(n, spec: LangSpec) -> bool:
    """Is an annotation before the item (comments between allowed) the language's test-only marker?"""
    p = n.prev_named_sibling
    while p is not None and (p.type in spec.annotations or p.type in spec.comments):
        if p.type in spec.annotations and re.fullmatch(spec.test_only, text(p).strip()):
            return True
        p = p.prev_named_sibling
    return False


def _nested(decl, fn, name: str, scope: str, params: list[dict]) -> dict:
    """A named function inside a function: not a node, but structure makes it one when a route names it."""
    return {"name": name, "start": decl.start_point[0] + 1, "line": decl.start_point[0] + 1,
            "end": decl.end_point[0] + 1, "in": scope, "params": params}


class Adapter:
    """`parse` with the language table bound, the shape structure.LANGS expects of an adapter module."""

    def __init__(self, spec: LangSpec) -> None:
        self.spec = spec

    def parse(self, src: bytes, rel_file: str, module: dict, reg: ids.IdRegistry, st=None) -> dict:
        return parse(src, rel_file, module, reg, st, spec=self.spec)
