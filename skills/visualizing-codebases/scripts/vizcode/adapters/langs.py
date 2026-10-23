"""Language tables for the generic walker (adapters/generic.py): data only, one LangSpec per language.

A *key* names a child of a node: a grammar field name; failing that, the type of a named child (for grammars
without fields, e.g. Kotlin); "" means the first named child whose type ends in `identifier`. Where a field takes
several keys, the first present wins.

lang          map language name ("java")
grammar       tree-sitter language name
suffixes      file suffixes
sep           import/package separator: "." | "/" | "::" | "\\"
package       node types holding the package/namespace (name: the `name` key, else the first named child), or
              "dir": the folder relative to the module (`_root_` at the module root); "dir" last in the tuple =
              that folder when no such node is found (Ruby, PHP). A package node at the top that is also a class
              type (Ruby's outermost `module`) is not a class
classes       class-like node type -> name key
functions     function node type -> name key; a function inside a class is its method, else the file's
params        (keys of the parameter list, node types that count as one parameter); a key naming a lone
              parameter (JS `x => x`) is that one parameter
returns       keys of a function's return type (() when the grammar writes none)
imports       import node type -> a key of generic.IMPORT_READERS; a reader finding nothing (a call that is not
              `require`) leaves the node to the other fields
calls         call node type -> (callee keys: the callee is the source text from the first to the last present,
              type arguments left out; path of keys to the argument list)
strings       string literal node types (quotes stripped; interpolations as {..})
annotations   annotation/decorator/attribute node types, found before a declaration's name or as the
              preceding siblings of the declaration
env           regex over the source, the first group that matched = environment key
private       regex over a declaration's modifier text and name (annotations left out) meaning private
upper_exported  a name is public only when its first character is upper case (`str.isupper`, any script: Go)
tests         test file name globs
group_depth   import segments naming a library in the Stack section
variadic      parameter node types, types of a parameter's name, or marker tokens before a parameter (Kotlin
              `vararg`, C# `params`) taking any count (recorded as `*name`, as Python's *args)
splats        argument node types (or their child) that hide the count of a call
interpolations string child node types read as {..}
interpolation_marks  string child node types that only delimit an interpolation (dropped)
types         node types writing a parameter's type, for grammars without a `type` field
supers        keys under a class whose children name what it extends or implements (`parent/child`: a child's)
bindings      declarator node type -> (name key, value key, value node types): a name bound to a function value
              (`const f = () => ...`) is a function named after it; other values are not
file_qualified  class ids start with the file stem (`<pkg>.<stem>.<Name>`): a folder package may hold two
              files defining one name
names         node types that are a parameter's name (a destructured or default parameter is named by its
              key or left side)
type_names    node types naming a type as written (supers); type_args inside are left out
type_args     type argument node types, left out of supers and callees
not_supers    node types under a supers key that name nothing it extends (argument lists, calls)
comments      comment node types
wildcards     node types marking a wildcard import
bare_strings  string node types without delimiters: the whole node is the contents (heredoc bodies)
attach        node type -> keys to the type whose class its functions join (Go receiver, Rust `impl`): a
              function node is that one method; any other node holds the methods. One class node per type;
              a type no file declares gets one at the first such node (structure pass)
attach_types  node types the attached-to type must be (after looking through `attach_unwrap` types' `type`) for a
              class to hold the methods; any other (a tuple, a type parameter named in the node's
              `attach_params` list: a blanket Rust `impl<T> X for T`) leaves them on the file node. () = any
attach_unwrap node types looked through to their `type` field (Rust `&T`)
attach_params key of the attach node's type parameter list
public_in     container node types whose members are public whatever is written (interfaces, traits);
              `type/key`: only when the container has that child (Rust `impl_item/trait`)
member_access regex over a class member's modifier text naming an access level; a member without one is
              private (C#). "" = off
sections      bare word in a class body -> visibility of the members after it (Ruby `private`)
declared_package  node types declaring a package name that "dir" checks against the folder's last segment;
              a mismatch is kept as FileResult `package_declared`
self_name     keys from a method node to the name of its own object when the code names it (Go receiver `r` in
              `func (r *Repo) X()`): a call on it is a call on `self` (call fact `self`)
class_when    class node type -> (key, node types): that type is a class only when its key child is one of these
              (TypeScript `type X = { ... }` is a class; `type Id = string` is not)
names_extend  an import's names continue its target (`a.b` + `C` = `a.b.C`); False: they are what the target
              exports (JS `import {a} from "x"`), and the target alone names the library
aliases       node type -> name key of a type alias that is no class (`type Id = string`, `typealias`, C#
              `using X = A.B;`): FileResult `aliases`, names a type link never resolves in that file
class_params  (keys of a class's own parameter list, node types that count as one parameter): a class written with
              one (Kotlin's primary constructor, C# 12 `class Orders(IRepo repo)`) is built from it, recorded as its
              `ctor`
value_classes keywords before a class's name (annotations left out) making it a value whose own parameters are its
              fields (Kotlin `data`, a Java or C# `record`, a Java `enum`): FileResult `values`; it gets no `ctor`,
              whatever constructors it declares
class_inits   function node type -> keyword before its name making it the class's own one-time initializer, not a
              constructor (C# `static Orders()`): FileResult `class_inits`, never a class's `ctor`
test_only     regex over an annotation before an item marking it test-only code (Rust `#[cfg(test)]`): the item
              and everything in it are left out. "" = off
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace


@dataclass(frozen=True, eq=False)
class LangSpec:
    lang: str
    grammar: str
    suffixes: tuple[str, ...]
    sep: str
    package: tuple[str, ...] | str
    classes: dict[str, str]
    functions: dict[str, str]
    params: tuple[tuple[str, ...], tuple[str, ...]]
    returns: tuple[str, ...]
    imports: dict[str, str]
    calls: dict[str, tuple[tuple[str, ...], tuple[str, ...]]]
    strings: tuple[str, ...]
    annotations: tuple[str, ...]
    env: str
    private: str
    tests: tuple[str, ...]
    group_depth: int
    variadic: tuple[str, ...] = ()
    splats: tuple[str, ...] = ()
    interpolations: tuple[str, ...] = ()
    interpolation_marks: tuple[str, ...] = ()
    types: tuple[str, ...] = ()
    supers: tuple[str, ...] = ()
    bindings: dict[str, tuple[str, str, tuple[str, ...]]] = field(default_factory=dict)
    file_qualified: bool = False
    names: tuple[str, ...] = ("identifier", "simple_identifier")
    type_names: tuple[str, ...] = ("type_identifier", "scoped_type_identifier", "identifier", "qualified_name",
                                   "user_type", "generic_type", "generic_name", "member_expression",
                                   "nested_type_identifier")
    type_args: tuple[str, ...] = ("type_arguments", "type_argument_list")
    not_supers: tuple[str, ...] = ("arguments", "argument_list", "value_arguments", "call_expression")
    comments: tuple[str, ...] = ("comment", "line_comment", "block_comment")
    wildcards: tuple[str, ...] = ("asterisk", "wildcard_import")
    bare_strings: tuple[str, ...] = ()
    attach: dict[str, tuple[str, ...]] = field(default_factory=dict)
    attach_types: tuple[str, ...] = ()
    attach_unwrap: tuple[str, ...] = ()
    attach_params: str = ""
    public_in: tuple[str, ...] = ()
    member_access: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    declared_package: tuple[str, ...] = ()
    upper_exported: bool = False
    self_name: tuple[str, ...] = ()
    names_extend: bool = True
    class_when: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    class_params: tuple[tuple[str, ...], tuple[str, ...]] = ((), ())
    value_classes: tuple[str, ...] = ()
    class_inits: dict[str, str] = field(default_factory=dict)
    test_only: str = ""


JAVA = LangSpec(
    lang="java", grammar="java", suffixes=(".java",), sep=".",
    package=("package_declaration",),
    classes={"class_declaration": "name", "interface_declaration": "name", "enum_declaration": "name",
             "record_declaration": "name", "annotation_type_declaration": "name"},
    functions={"method_declaration": "name", "constructor_declaration": "name",
               "compact_constructor_declaration": "name"},
    params=(("parameters",), ("formal_parameter", "spread_parameter")),
    returns=("type",),
    imports={"import_declaration": "qualified-name"},
    calls={"method_invocation": (("object", "name"), ("arguments",)),
           "object_creation_expression": (("type",), ("arguments",))},
    strings=("string_literal",),
    annotations=("annotation", "marker_annotation"),
    env=r'System\.getenv\(\s*"([A-Za-z0-9_]+)"',
    private=r"\b(private|protected)\b",
    tests=("*Test.java", "*Tests.java", "*IT.java"),
    group_depth=2,
    variadic=("spread_parameter",),
    types=("type_identifier", "generic_type", "scoped_type_identifier", "integral_type", "floating_point_type",
           "boolean_type", "array_type"),
    supers=("superclass", "interfaces", "extends_interfaces"),
    value_classes=("record", "enum"),
)

KOTLIN_TYPES = ("user_type", "nullable_type", "function_type")
KOTLIN = LangSpec(
    lang="kotlin", grammar="kotlin", suffixes=(".kt", ".kts"), sep=".",
    package=("package_header",),
    classes={"class_declaration": "", "object_declaration": ""},
    aliases={"type_alias": ""},
    functions={"function_declaration": ""},
    params=(("function_value_parameters",), ("parameter",)),
    returns=KOTLIN_TYPES,
    imports={"import_header": "qualified-name"},
    calls={"call_expression": (("simple_identifier", "navigation_expression"), ("call_suffix", "value_arguments"))},
    strings=("string_literal",),
    annotations=("annotation",),
    env=r'System\.getenv\(\s*"([A-Za-z0-9_]+)"',
    private=r"\b(private|protected)\b",
    tests=("*Test.kt", "*Tests.kt"),
    group_depth=2,
    variadic=("vararg",),
    splats=("spread_expression",),
    interpolations=("interpolated_identifier", "interpolated_expression"),
    interpolation_marks=("interpolation_identifier_start", "interpolation_expression_start",
                         "interpolation_expression_end"),
    types=KOTLIN_TYPES,
    supers=("delegation_specifier",),
    class_params=(("primary_constructor",), ("class_parameter",)),
    value_classes=("data", "value", "enum", "annotation"),
)

CSHARP = LangSpec(
    lang="csharp", grammar="csharp", suffixes=(".cs",), sep=".",
    package=("file_scoped_namespace_declaration", "namespace_declaration"),
    classes={"class_declaration": "name", "interface_declaration": "name", "record_declaration": "name",
             "struct_declaration": "name", "enum_declaration": "name"},
    aliases={"using_directive": "name"},
    functions={"method_declaration": "name", "constructor_declaration": "name"},
    params=(("parameters",), ("parameter",)),
    returns=("returns",),
    imports={"using_directive": "whole-name"},
    calls={"invocation_expression": (("function",), ("arguments",)),
           "object_creation_expression": (("type",), ("arguments",))},
    strings=("string_literal", "verbatim_string_literal", "interpolated_string_expression", "raw_string_literal"),
    annotations=("attribute_list",),
    env=r'Environment\.GetEnvironmentVariable\(\s*"([A-Za-z0-9_]+)"',
    private=r"\b(private|protected)\b",
    tests=("*Tests.cs", "*Test.cs"),
    group_depth=2,
    variadic=("params",),
    interpolations=("interpolation",),
    interpolation_marks=("interpolation_brace",),
    supers=("base_list",),
    class_params=(("parameter_list",), ("parameter",)),
    value_classes=("record",),
    class_inits={"constructor_declaration": "static"},
    public_in=("interface_declaration",),
    member_access=r"\b(public|internal|protected|private)\b",
)

JS_NAMES = ("identifier", "shorthand_property_identifier_pattern", "property_identifier")
JS_FUNCTION_VALUES = ("arrow_function", "function_expression", "generator_function")
JS_ENV = r'process\.env(?:\.([A-Za-z_]\w*)|\[\s*["\'`]([A-Za-z0-9_]+)["\'`]\s*\])'
TYPESCRIPT = LangSpec(
    lang="typescript", grammar="typescript", suffixes=(".ts",), sep="/",
    package="dir",
    classes={"class_declaration": "name", "abstract_class_declaration": "name", "interface_declaration": "name",
             "enum_declaration": "name", "type_alias_declaration": "name"},
    functions={"function_declaration": "name", "generator_function_declaration": "name",
               "method_definition": "name", "method_signature": "name", "abstract_method_signature": "name"},
    params=(("parameters", "parameter"), ("required_parameter", "optional_parameter", "identifier")),
    returns=("return_type",),
    imports={"import_statement": "es-module", "export_statement": "es-module", "call_expression": "require"},
    calls={"call_expression": (("function",), ("arguments",)), "new_expression": (("constructor",), ("arguments",))},
    strings=("string", "template_string"),
    annotations=("decorator",),
    env=JS_ENV,
    private=r"\b(private|protected)\b|(?:^|\s)#",
    tests=("*.test.ts", "*.spec.ts", "*.test.tsx", "*.spec.tsx", "*.e2e.ts", "*.e2e-*.ts", "__tests__/*", "e2e/*"),
    group_depth=1,
    variadic=("rest_pattern",),
    splats=("spread_element",),
    interpolations=("template_substitution",),
    supers=("class_heritage", "extends_type_clause"),
    names=JS_NAMES,
    bindings={"variable_declarator": ("name", "value", JS_FUNCTION_VALUES),
              "public_field_definition": ("name", "value", JS_FUNCTION_VALUES),
              "assignment_expression": ("left", "right", JS_FUNCTION_VALUES),
              "pair": ("key", "value", JS_FUNCTION_VALUES)},   # `{ me: async () => .. }`: an object's method,
    file_qualified=True,
    names_extend=False,
    class_when={"type_alias_declaration": ("value", ("object_type",))},
    aliases={"type_alias_declaration": "name"},
)
TSX = replace(TYPESCRIPT, grammar="tsx", suffixes=(".tsx",))

JAVASCRIPT = replace(
    TYPESCRIPT, lang="javascript", grammar="javascript", suffixes=(".js", ".jsx", ".mjs", ".cjs"),
    classes={"class_declaration": "name"},
    functions={"function_declaration": "name", "generator_function_declaration": "name",
               "method_definition": "name"},
    params=(("parameters", "parameter"), ("identifier", "assignment_pattern", "rest_pattern", "object_pattern",
                                          "array_pattern")),
    returns=(),
    private=r"(?:^|\s)#",
    tests=("*.test.js", "*.spec.js", "*.test.jsx", "*.spec.jsx", "*.e2e.js", "*.e2e-*.js", "__tests__/*", "e2e/*"),
    supers=("class_heritage",),
    bindings={"variable_declarator": ("name", "value", JS_FUNCTION_VALUES),
              "field_definition": ("property", "value", JS_FUNCTION_VALUES),
              "assignment_expression": ("left", "right", JS_FUNCTION_VALUES),
              "pair": ("key", "value", JS_FUNCTION_VALUES)},   # `{ me: async () => .. }`: an object's method,
)

GO = LangSpec(
    lang="go", grammar="go", suffixes=(".go",), sep="/",
    package="dir",
    classes={"type_spec": "name"},
    aliases={"type_alias": "name"},
    functions={"function_declaration": "name", "method_declaration": "name", "method_elem": "name"},
    params=(("parameters",), ("parameter_declaration", "variadic_parameter_declaration")),
    returns=("result",),
    imports={"import_declaration": "go-import"},
    calls={"call_expression": (("function",), ("arguments",))},
    strings=("interpreted_string_literal", "raw_string_literal"),
    annotations=(),
    env=r'os\.(?:Getenv|LookupEnv)\(\s*"([A-Za-z0-9_]+)"',
    private=r"(?!)",
    tests=("*_test.go",),
    group_depth=3,
    variadic=("variadic_parameter_declaration",),
    splats=("variadic_argument",),
    attach={"method_declaration": ("receiver", "parameter_declaration", "type")},
    declared_package=("package_clause",),
    upper_exported=True,
    self_name=("receiver", "parameter_declaration", "name"),
)

RUST = LangSpec(
    lang="rust", grammar="rust", suffixes=(".rs",), sep="::",
    package="dir",
    classes={"struct_item": "name", "enum_item": "name", "union_item": "name", "trait_item": "name",
             "mod_item": "name"},
    aliases={"type_item": "name"},
    functions={"function_item": "name", "function_signature_item": "name"},
    params=(("parameters",), ("parameter",)),
    returns=("return_type",),
    imports={"use_declaration": "rust-use", "mod_item": "rust-mod"},
    calls={"call_expression": (("function",), ("arguments",))},
    strings=("string_literal", "raw_string_literal"),
    annotations=("attribute_item",),
    env=r'env::var(?:_os)?\(\s*"([A-Za-z0-9_]+)"',
    private=r"^(?!\s*pub\b)",
    tests=("tests/*", "tests.rs", "test.rs"),   # the files of `#[cfg(test)] mod tests;`
    group_depth=1,
    supers=("trait", "bounds"),
    file_qualified=True,
    test_only=r"#\[cfg\(\s*test\s*\)\]",
    attach={"impl_item": ("type",)},
    attach_types=("type_identifier", "scoped_type_identifier", "generic_type"),
    attach_unwrap=("reference_type",),
    attach_params="type_parameters",
    public_in=("trait_item", "impl_item/trait"),
)

RUBY = LangSpec(
    lang="ruby", grammar="ruby", suffixes=(".rb",), sep="/",
    package=("module", "dir"),
    classes={"class": "name", "module": "name"},
    functions={"method": "name", "singleton_method": "name"},
    params=(("parameters",), ("identifier", "optional_parameter", "splat_parameter", "hash_splat_parameter",
                              "keyword_parameter", "destructured_parameter")),
    returns=(),
    imports={"call": "ruby-require"},
    calls={"call": (("receiver", "method"), ("arguments",))},
    strings=("string", "heredoc_body"),
    annotations=(),
    env=r'\bENV(?:\[\s*["\']([A-Za-z0-9_]+)["\']\s*\]|\.fetch[\s(]\s*["\']([A-Za-z0-9_]+)["\'])',
    private=r"(?!)",
    tests=("*_spec.rb", "*_test.rb", "test_*.rb", "spec/*"),
    group_depth=1,
    variadic=("splat_parameter", "hash_splat_parameter"),
    splats=("splat_argument", "hash_splat_argument", "block_argument"),
    interpolations=("interpolation",),
    interpolation_marks=("heredoc_end",),
    supers=("superclass",),
    type_names=("constant", "scope_resolution"),
    bare_strings=("heredoc_body",),
    sections={"private": "private", "protected": "private", "public": "public"},
)

PHP = LangSpec(
    lang="php", grammar="php", suffixes=(".php",), sep="\\",
    package=("namespace_definition", "dir"),
    classes={"class_declaration": "name", "interface_declaration": "name", "trait_declaration": "name",
             "enum_declaration": "name"},
    functions={"method_declaration": "name", "function_definition": "name"},
    params=(("parameters",), ("simple_parameter", "variadic_parameter", "property_promotion_parameter")),
    returns=("return_type",),
    imports={"namespace_use_declaration": "php-use"},
    calls={"function_call_expression": (("function",), ("arguments",)),
           "member_call_expression": (("object", "name"), ("arguments",)),
           "nullsafe_member_call_expression": (("object", "name"), ("arguments",)),
           "scoped_call_expression": (("scope", "name"), ("arguments",)),
           "object_creation_expression": (("name", "qualified_name"), ("arguments",))},
    strings=("string", "encapsed_string", "heredoc_body", "nowdoc_body"),
    annotations=("attribute_list",),
    env=r'(?:\bgetenv|\benv)\(\s*["\']([A-Za-z0-9_]+)["\']|\$_ENV\[\s*["\']([A-Za-z0-9_]+)["\']\s*\]',
    private=r"\b(private|protected)\b",
    tests=("*Test.php",),
    group_depth=2,
    variadic=("variadic_parameter",),
    splats=("variadic_unpacking",),
    interpolations=("variable_name", "member_access_expression", "subscript_expression", "dynamic_variable_name",
                    "member_call_expression"),
    interpolation_marks=("{", "}"),
    supers=("base_clause", "class_interface_clause", "body/use_declaration"),
    not_supers=("use_list",),   # `use T { a as b; }`: the renames name methods
    names=("name",),
    type_names=("name", "qualified_name"),
    bare_strings=("heredoc_body", "nowdoc_body"),
)

ALL: tuple[LangSpec, ...] = (JAVA, KOTLIN, CSHARP, TYPESCRIPT, TSX, JAVASCRIPT, GO, RUST, RUBY, PHP)
SPECS: dict[str, LangSpec] = {s.lang: s for s in reversed(ALL)}      # by language: `.ts`'s table, not `.tsx`'s
BY_SUFFIX: dict[str, LangSpec] = {suf: s for s in ALL for suf in s.suffixes}
