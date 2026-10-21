"""Declared fields of a class, per language (spec: traces §1.1): `[{name, type}]` in declared order, `type` the
declared type text or None where the language declares none. A class with none gets no `fields` key."""
from __future__ import annotations

import re

from . import text
from .langs import JS_FUNCTION_VALUES, KOTLIN_TYPES


def _type(node) -> str | None:
    """The type text as written, without a leading `:` (TypeScript `type_annotation`); None without a node."""
    return (text(node).lstrip(":").strip() or None) if node is not None else None


def _tokens(node) -> set[str]:
    """Anonymous keyword children (`static`, `readonly`, `case`)."""
    return {c.type for c in node.children if not c.is_named}


def _named(node, name: str) -> bool:
    """The node's `name` child reads `name` (a node without one never does)."""
    n = node.child_by_field_name("name")
    return n is not None and text(n) == name


def _field(name: str, typ, visibility: str | None = None) -> dict:
    """One field; a quoted name (Scala, Kotlin backticks) without its quotes; `typ` a type node or None; `visibility`
    in the languages that say it by modifiers."""
    out = {"name": name.strip("`"), "type": _type(typ)}
    if visibility:
        out["visibility"] = visibility
    return out


MODIFIERS = ("modifiers", "modifier", "visibility_modifier", "access_modifier")
ACCESS = {"public", "protected", "private", "internal"}


def _access(decl, implicit: str = "public") -> str:
    """A member's visibility from its modifier keywords (annotations left out): `private` or `protected` make it
    private; with no access keyword it is `implicit` (C# members are private by default)."""
    words, stack = set(), [c for c in decl.children if c.type in MODIFIERS]
    while stack:
        n = stack.pop()
        if "annotation" in n.type:
            continue
        if n.is_named:
            stack.extend(n.children)
        else:
            words.add(n.type)
    if words & {"private", "protected"}:
        return "private"
    return "public" if words & ACCESS else implicit


# --- Scala, Python (own adapters) -------------------------------------------------------------------------

def scala(cls) -> list[dict]:
    """A case class's first parameter list; any other class has none."""
    if cls.type != "class_definition" or "case" not in _tokens(cls):
        return []
    lists = cls.children_by_field_name("class_parameters")
    if not lists or _tokens(lists[0]) & {"implicit", "using"}:
        return []
    return [_field(text(p.child_by_field_name("name")), p.child_by_field_name("type"), _access(p))
            for p in lists[0].named_children
            if p.type == "class_parameter" and p.child_by_field_name("name") is not None]


def python(cls) -> list[dict]:
    """Class-level annotated attributes (`x: int`, `x: int = 0`); `ClassVar[...]` ones are not fields."""
    body = cls.child_by_field_name("body")
    out = []
    for c in (body.named_children if body is not None else []):
        a = c.named_children[0] if c.type == "expression_statement" and c.named_children else c
        if a.type != "assignment":
            continue
        left, typ = a.child_by_field_name("left"), a.child_by_field_name("type")
        if left is None or typ is None or left.type != "identifier" or re.match(r"(typing\.)?ClassVar\b", text(typ)):
            continue
        out.append(_field(text(left), typ))
    return out


# --- generic-walker languages ------------------------------------------------------------------------------

def _java(cls) -> list[dict]:
    out = []
    plist = cls.child_by_field_name("parameters") if cls.type == "record_declaration" else None
    for p in (plist.named_children if plist is not None else []):
        if p.type == "formal_parameter" and (name := p.child_by_field_name("name")) is not None:
            out.append(_field(text(name), p.child_by_field_name("type"), "public"))
        elif p.type == "spread_parameter":      # `int... xs`: the type is the first child, the name a declarator
            decl = next((k for k in p.named_children if k.type == "variable_declarator"), None)
            typ = next((k for k in p.named_children if k.type != "variable_declarator"), None)
            if decl is not None and typ is not None and (name := decl.child_by_field_name("name")) is not None:
                out.append({"name": text(name), "type": text(typ) + "...", "visibility": "public"})
    body = cls.child_by_field_name("body")
    if cls.type not in ("class_declaration", "record_declaration") or body is None:
        return out
    for f in body.named_children:
        mods = next((c for c in f.named_children if c.type == "modifiers"), None)
        if f.type != "field_declaration" or (mods is not None and re.search(r"\bstatic\b", text(mods))):
            continue
        for d in f.children_by_field_name("declarator"):
            if (name := d.child_by_field_name("name")) is not None:
                out.append(_field(text(name), f.child_by_field_name("type"), _access(f)))
    return out


def _kotlin(cls) -> list[dict]:
    out = []
    for c in cls.named_children:
        if c.type == "primary_constructor":
            for p in c.named_children:
                if p.type == "class_parameter" and any(k.type == "binding_pattern_kind" for k in p.named_children):
                    name = next((k for k in p.named_children if k.type == "simple_identifier"), None)
                    typ = next((k for k in p.named_children if k.type in KOTLIN_TYPES), None)
                    if name is not None:
                        out.append(_field(text(name), typ, _access(p)))
        elif c.type == "class_body":
            for prop in c.named_children:
                if prop.type != "property_declaration":
                    continue
                var = next((k for k in prop.named_children if k.type == "variable_declaration"), None)
                name = next((k for k in var.named_children if k.type == "simple_identifier"), None) if var else None
                if name is not None:
                    typ = next((k for k in var.named_children if k.type in KOTLIN_TYPES), None)
                    out.append(_field(text(name), typ, _access(prop)))
    return out


def _ts_members(holder) -> list[dict]:
    """Interface members and object-type members: property signatures (method signatures are methods)."""
    return [_field(text(m.child_by_field_name("name")), m.child_by_field_name("type"))
            for m in holder.named_children
            if m.type == "property_signature" and m.child_by_field_name("name") is not None]


def _class_fields(body, field_type: str, name_key: str) -> list[dict]:
    """TS/JS class fields: not static, not a function value (a bound function is a method); a TypeScript
    constructor's parameter properties (`constructor(private repo: Repo)`) where they stand."""
    out = []
    for m in body.named_children:
        if m.type == field_type:
            value, name = m.child_by_field_name("value"), m.child_by_field_name(name_key)
            if name is None or "static" in _tokens(m) or (value is not None and value.type in JS_FUNCTION_VALUES):
                continue
            out.append(_field(text(name), m.child_by_field_name("type")))
        elif m.type == "method_definition" and _named(m, "constructor"):
            params = m.child_by_field_name("parameters")
            for p in (params.named_children if params is not None else []):
                marked = "readonly" in _tokens(p) or any(k.type == "accessibility_modifier" for k in p.named_children)
                if p.type in ("required_parameter", "optional_parameter") and marked \
                        and (pat := p.child_by_field_name("pattern")) is not None and pat.type == "identifier":
                    out.append(_field(text(pat), p.child_by_field_name("type")))
    return out


def _typescript(cls) -> list[dict]:
    if cls.type == "interface_declaration":
        body = cls.child_by_field_name("body")
        return _ts_members(body) if body is not None else []
    if cls.type == "type_alias_declaration":
        value = cls.child_by_field_name("value")
        return _ts_members(value) if value is not None and value.type == "object_type" else []
    body = cls.child_by_field_name("body")
    return _class_fields(body, "public_field_definition", "name") if body is not None else []


def _javascript(cls) -> list[dict]:
    body = cls.child_by_field_name("body")
    return _class_fields(body, "field_definition", "property") if body is not None else []


def _go(cls) -> list[dict]:
    """Struct fields; an embedded field is named by its type (`*pkg.Base` -> Base)."""
    st = cls.child_by_field_name("type")
    if st is None or st.type != "struct_type":
        return []
    out = []
    for fl in st.named_children:
        for f in (fl.named_children if fl.type == "field_declaration_list" else []):
            if f.type != "field_declaration":
                continue
            typ = f.child_by_field_name("type")
            names = f.children_by_field_name("name")
            if names:
                out += [_field(text(n), typ) for n in names]
            elif typ is not None and (m := re.search(r"(\w+)\W*$", re.sub(r"\[.*\]\s*$", "", text(typ)))):
                out.append(_field(m.group(1), typ))
    return out


def _csharp(cls) -> list[dict]:
    out = []
    if cls.type == "record_declaration":
        plist = next((c for c in cls.named_children if c.type == "parameter_list"), None)
        for p in (plist.named_children if plist is not None else []):
            if p.type == "parameter" and (name := p.child_by_field_name("name")) is not None:
                out.append(_field(text(name), p.child_by_field_name("type"), "public"))
    body = cls.child_by_field_name("body")
    implicit = "public" if cls.type == "interface_declaration" else "private"
    for m in (body.named_children if body is not None else []):
        if m.type == "property_declaration" and not any(
                k.type == "modifier" and text(k) == "static" for k in m.named_children):
            if (name := m.child_by_field_name("name")) is not None:
                out.append(_field(text(name), m.child_by_field_name("type"), _access(m, implicit)))
    return out


def _rust(cls) -> list[dict]:
    """Named struct fields; a tuple struct's fields are `0`, `1`, ...."""
    body = cls.child_by_field_name("body")
    if cls.type not in ("struct_item", "union_item") or body is None:
        return []
    if body.type == "field_declaration_list":
        return [_field(text(f.child_by_field_name("name")), f.child_by_field_name("type"))
                for f in body.named_children
                if f.type == "field_declaration" and f.child_by_field_name("name") is not None]
    return [_field(str(i), t) for i, t in enumerate(body.children_by_field_name("type"))]


def _php(cls) -> list[dict]:
    """Typed, non-static properties; promoted constructor parameters (typed or not)."""
    body = cls.child_by_field_name("body")
    out = []
    for m in (body.named_children if body is not None else []):
        if m.type == "property_declaration" and m.child_by_field_name("type") is not None \
                and not any(k.type == "static_modifier" for k in m.named_children):
            for el in m.named_children:
                if el.type == "property_element" and (name := el.child_by_field_name("name")) is not None:
                    out.append(_field(text(name).lstrip("$"), m.child_by_field_name("type"), _access(m)))
        elif m.type == "method_declaration" and _named(m, "__construct"):
            params = m.child_by_field_name("parameters")
            for p in (params.named_children if params is not None else []):
                if p.type == "property_promotion_parameter" and (name := p.child_by_field_name("name")) is not None:
                    out.append(_field(text(name).lstrip("$"), p.child_by_field_name("type"), _access(p)))
    return out


READERS = {"java": _java, "kotlin": _kotlin, "typescript": _typescript, "javascript": _javascript, "go": _go,
           "csharp": _csharp, "rust": _rust, "php": _php}     # Ruby declares no fields


def read(lang: str, cls) -> list[dict]:
    """The declared fields of a class node of a generic-walker language ([] when none)."""
    reader = READERS.get(lang)
    return reader(cls) if reader is not None else []
