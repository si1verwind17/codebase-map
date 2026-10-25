"""Method-to-method `calls` relations, resolved by name from the structure pass's call sites."""
from __future__ import annotations

import functools
import re

from . import ids
from .adapters import without_suffix

MAX_CANDIDATES = 3
SELF_RECEIVERS = {"self", "this", "cls"}
# methods every object has: on a value of unknown type that names no repo class the call is to its own class or a
# library's, never matched to a repo method by name
OBJECT_METHODS = {"equals", "hashCode", "toString", "compareTo", "clone", "getClass", "Equals", "GetHashCode",
                  "ToString", "CompareTo", "String", "__str__", "__repr__", "__eq__", "__hash__", "__lt__",
                  "to_string", "to_s", "eql?", "fmt", "eq"}
# languages whose class header does not list everything a method can come from (Go embedding, Ruby `include`,
# Rust `impl Trait for T` anywhere in the crate graph and `Deref`); for a self call also Scala's self-types
# (`self: Repo =>`)
OPEN_LINEAGE = {"go", "ruby", "rust"}
OPEN_SELF = OPEN_LINEAGE | {"scala"}
# languages where a bare call (`helper()`) is never a method of a class: no implicit `this`
# languages whose free functions never take a value as receiver (Kotlin, Scala: extension functions; Ruby: a mixin
# module's methods sit on its file; JS/TS: a `require()` binding the scan may not record)
VALUE_METHODS = {"python", "go", "rust", "java", "csharp", "php"}
NO_IMPLICIT_THIS = {"php", "python", "javascript", "typescript", "go"}   # Rust: a `mod`'s functions are class-like
# value names too generic to name a class by their tail (`list.get` is no PagedList)
GENERIC_VALUES = {"list", "map", "set", "data", "item", "items", "result", "results", "value", "values", "obj",
                  "object", "entry", "entries", "response", "request", "config", "info", "node", "element", "array"}
LITERAL_RECEIVER = re.compile(r"""\s*(?:["'`]|\d)""")   # `"\n".join`, `5.times`: a built-in type's method
PART = re.compile(r"~\d+$")   # `Foo~2`: another part of class Foo (C# `partial`, a class reopened elsewhere)
# words of a value's name that say its role, not which class it holds: `emailRepo` holds the email class
ROLE_NAMES = {"repo", "repository", "model", "service", "svc", "dao", "store", "client", "manager", "impl",
              "provider", "gateway", "handler", "controller", "helper"}
CAMEL = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
IDENT = re.compile(r"[A-Za-z_]\w*")
TYPE_WORD = re.compile(r"[A-Za-z_][\w.]*")
TYPE_SKIP = {"mut", "const", "final", "in", "out", "ref", "dyn", "impl", "readonly", "var", "val",
             "None", "null", "undefined"}   # `None | Order`, `undefined | Order`: the type is the other side
# wrappers a value is used through as the type inside them (`Arc<dyn Repo>`, `Annotated[Repo, Depends(..)]`)
TYPE_UNWRAP = {"Optional", "Annotated", "Box", "Arc", "Rc", "RefCell", "Mutex", "RwLock", "Pin", "Readonly",
               "Partial", "Required", "NonNullable"}
# collections and futures: a call on one is the library's method, whatever repo type it holds (`orders.get(0)`)
TYPE_CONTAINERS = {"list", "List", "dict", "Dict", "set", "Set", "tuple", "Tuple", "Sequence", "Iterable", "Mapping",
                   "Map", "HashMap", "Seq", "Vector", "Vec", "Array", "ArrayList", "Collection", "Iterator",
                   "Promise", "Future", "Task", "IO", "ZIO", "Option", "Either", "Result", "Mono", "Flux",
                   "Observable", "Stream", "IEnumerable", "IList", "Dictionary", "MutableList", "MutableMap"}
QUOTED = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
CHAINED = re.compile(r"[)\]}]\s*\.\s*[\w!?]+\s*$")   # `build(x).run`: a method of a call's result


def callee_parts(callee: str) -> list[str]:
    """Identifiers of the called expression only: string literals and bracketed argument text are dropped
    (`ZIO.when(a.fill)` → ZIO, when; `super().save` → super, save)."""
    text, out, depth = QUOTED.sub("\x00", callee), [], 0
    for ch in text:
        if ch in "([{":
            depth += 1
            if depth == 1:
                out.append("\x00")   # where a bracket group stood
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    flat = "".join(out).lstrip()
    parts = IDENT.findall(flat)
    # `", ".join`, `{}.get`, `(a or b).save`: the receiver was a literal or an expression: never trust it
    if flat.startswith("\x00") and parts:
        return ["?"] + parts
    return parts


COPY_FILES = 3          # a top-level function defined in this many files of one service reads as copy-paste
COPY_EXEMPT = {"main", "run", "handler", "lambda_handler", "setup", "teardown"}


def _package(nid: str, by_id: dict[str, dict]) -> str | None:
    n = by_id.get(nid)
    while n is not None and n["kind"] not in ("package", "service", "library"):
        n = by_id.get(n.get("parent") or "")
    return n["id"] if n is not None and n["kind"] == "package" else None


def _copy_paste(index: dict[str, dict[str, list[str]]], by_id: dict[str, dict]) -> list[dict]:
    """Problems for top-level functions repeated across files: the map should show the smell, not hide it."""
    out = []
    for rt, names in sorted(index.items()):
        repeated = []
        for name, ms in names.items():
            files = {by_id[m].get("file") for m in ms if (by_id.get(by_id[m].get("parent") or "") or {}).get("kind") == "file"}
            if len(files) >= COPY_FILES and name not in COPY_EXEMPT and not name.startswith("__"):
                repeated.append((len(files), name))
        if repeated:
            repeated.sort(key=lambda kv: (-kv[0], kv[1]))
            shown = ", ".join(f"`{n}` ×{k}" for k, n in repeated[:6]) + (" …" if len(repeated) > 6 else "")
            out.append({"text": f"{len(repeated)} function(s) in {rt} are each defined in {COPY_FILES}+ files, likely "
                                f"copy-paste ({shown}); calls resolve to the caller's own file",
                        "nodes": [rt], "source": "assemble"})
    return out


OPTIONAL_RECORDED = {"python", "scala"}   # adapters that mark the parameters a call may leave out (`optional`)


def _accepts(method: dict, n: int) -> bool:
    """Can `method` take n arguments? Unknown signatures, *args/**kw (and the variadics other languages record so) and
    a Scala repeated parameter (`params: Any*`) take any count. Where the adapter marks optional parameters, a call
    must also pass every required one."""
    params = (method.get("signature") or {}).get("params")
    if params is None or any(p["name"].startswith("*") or (p.get("type") or "").endswith("*") for p in params):
        return True
    required = sum(not p.get("optional") for p in params) if method.get("lang") in OPTIONAL_RECORDED else 0
    return required <= n <= len(params)


def _outer_type(type_text: str | None) -> str | None:
    """The outermost type name of a declared type (`Map<String, Object>` -> Map, `*orders.Handler` -> Handler,
    `Optional[Order]` -> Order, `&mut Repo` -> Repo), or None when there is none."""
    words = [w.rsplit(".", 1)[-1] for w in TYPE_WORD.findall(type_text or "") if w not in TYPE_SKIP]
    while len(words) > 1 and words[0] in TYPE_UNWRAP:
        words = words[1:]
    return words[0] if words else None


def _param_type(method: dict, name: str) -> tuple[str, list[str]] | None:
    """(outer type name, repo class ids it names) of the caller's parameter called `name` that declares a type."""
    for p in (method.get("signature") or {}).get("params", []):
        if p.get("name") == name and (outer := _outer_type(p.get("type"))):
            return outer, p.get("refs") or []
    return None


def _field_type(owner: dict | None, name: str) -> tuple[str, list[str]] | None:
    """(outer type name, repo class ids it names) of the caller's class field, or constructor parameter (Scala and
    Kotlin class parameters, a C# primary constructor: `class Live(db: Jdbc)`), called `name` that declares a type."""
    for f in (owner or {}).get("fields") or []:
        if f.get("name") == name and (outer := _outer_type(f.get("type"))):
            return outer, []
    for p in ((owner or {}).get("ctor") or {}).get("params") or []:
        if p.get("name") == name and (outer := _outer_type(p.get("type"))):
            return outer, p.get("refs") or []
    return None


def _subject(name: str) -> tuple[str, ...]:
    """The words of a class or value name without its role words: `EmailModel`, `emailRepo` -> ("email",)."""
    words = tuple(w.lower() for w in CAMEL.findall(name.replace("_", " ")))
    return tuple(w for w in words if w not in ROLE_NAMES) or words


def _ancestors(cid: str, by_id: dict[str, dict]) -> set[str]:
    """A class and every class it extends or implements in the repo."""
    out, todo = set(), [cid]
    while todo:
        c = todo.pop()
        if c not in out and c in by_id:
            out.add(c)
            todo += by_id[c].get("implements") or []
    return out


def _sig_refs(method: dict) -> set[str]:
    sig = method.get("signature") or {}
    return {r for p in sig.get("params", []) for r in p.get("refs") or []} | set(sig.get("returns_refs") or [])


def _context_refs(caller: dict, by_id: dict[str, dict], spans: dict[str, list[dict]]) -> set[str]:
    """Repo types the caller's declarations name: its own signature's, and those of the methods and vals around it
    in its file (`val live: Layer[Chain[AKey], X] = ... new X { def apply(..) }`), less the caller's own types."""
    line, out = caller.get("line", 0), _sig_refs(caller)
    for m in spans.get(caller.get("file") or "", []):
        if m is not caller and m.get("line", 0) <= line < m.get("line", 0) + (m.get("metrics") or {}).get("loc", 1):
            out |= _sig_refs(m)
    return out - _ancestors(caller.get("parent") or "", by_id)   # what the caller is, not what it holds


def _narrowed(cands: list[str], context: set[str], by_id: dict[str, dict]) -> list[str]:
    """The candidates whose class descends from a type the caller's declarations name, when that tells them apart:
    ancestors every candidate shares (the interface they all implement) do not count."""
    if len(cands) < 2 or not context:
        return cands
    ancestry = {m: _ancestors(by_id[m].get("parent") or "", by_id) for m in cands}
    shared = set.intersection(*ancestry.values())
    keep = [m for m in cands if (ancestry[m] - shared) & context]
    return keep if 0 < len(keep) < len(cands) else cands


def _name_tails(name: str) -> set[str]:
    """The lower-cased runs of whole words that end a class name: `InMemoryListState` -> state, liststate, ..."""
    words = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+", without_suffix(name).rstrip("$"))
    return {"".join(words[i:]).lower() for i in range(len(words))}


def _owner_names(node: dict, nodes: dict[str, dict]) -> set[str]:
    """Lower-cased names of the class/file holding a method, used to trust `Receiver.method`."""
    parent = nodes.get(node.get("parent") or "")
    if not parent:
        return set()
    name = without_suffix(parent["name"].lower())
    return {name, name.rstrip("$")}


def _abstractions(by_id: dict[str, dict]) -> dict[str, str]:
    """Method id -> the method it implements: a same-named method of a class or trait in `implements`, or of the
    nearest class above one that declares it (an abstract class between them need not), followed upward, so a
    chain of implementations reaches the top. A trait method and its implementations count as one call target,
    drawn to the trait method."""
    methods: dict[str, dict[str, list[str]]] = {}
    for n in by_id.values():
        if n["kind"] == "method" and n.get("parent"):
            methods.setdefault(n["parent"], {}).setdefault(n["name"], []).append(n["id"])

    def declared(sup: str, name: str) -> list[str]:
        todo, seen = [sup], set()
        while todo:
            c = todo.pop(0)
            if c in seen or c not in by_id:
                continue
            seen.add(c)
            if found := methods.get(c, {}).get(name):
                return found
            todo += by_id[c].get("implements") or []
        return []

    up: dict[str, str] = {}
    for n in by_id.values():
        for sup in n.get("implements") or []:
            for name, mine in methods.get(n["id"], {}).items():
                theirs = declared(sup, name)
                for m in mine:
                    arity = m.rsplit("/", 1)[-1]
                    same = [t for t in theirs if t.rsplit("/", 1)[-1] == arity] or theirs
                    if len(same) == 1 and m not in up:
                        up[m] = same[0]

    def top(m: str) -> str:
        seen = {m}
        while m in up and up[m] not in seen:
            m = up[m]
            seen.add(m)
        return m

    return {m: top(m) for m in up}


def _id_name(nid: str) -> str:
    return nid.split("#", 1)[1].rsplit("/", 1)[0] if "#" in nid else ""


def _dag_scopes(by_id: dict[str, dict]) -> dict[str, tuple]:
    """Qualified Airflow tasks (`<file>#<dag>.<task>/n`, named `<task>`) -> (file node, DAG prefix, DAG
    function line spans). Such a task is a call target only from inside its own DAG."""
    out = {}
    for n in by_id.values():
        name = _id_name(n["id"])
        if n["kind"] == "method" and "." in name and name.endswith("." + n["name"]):
            prefix = name[: -len(n["name"]) - 1]
            spans = [(m["line"], m["line"] + (m.get("metrics") or {}).get("loc", 1) - 1) for m in by_id.values()
                     if m["kind"] == "method" and m.get("parent") == n.get("parent") and _id_name(m["id"]) == prefix]
            out[n["id"]] = (n.get("parent"), prefix, spans)
    return out


def _in_scope(caller: dict, scope: tuple) -> bool:
    owner, prefix, spans = scope
    if caller.get("parent") != owner:
        return False
    name = _id_name(caller["id"])
    if name == prefix or name.startswith(prefix + "."):
        return True
    return any(a <= caller.get("line", 0) <= b for a, b in spans)


def resolve(nodes: list[dict], relations: list[dict], facts: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Return (calls relations, problems). Candidates come from the caller's service or library
    and the libraries it uses; a unique match with a trusted receiver is confirmed, other
    matches are inferred, and call sites matching more than MAX_CANDIDATES methods are dropped."""
    by_id = {n["id"]: n for n in nodes}
    abstract = _abstractions(by_id)
    scoped = _dag_scopes(by_id)
    # names a capitalized receiver may point at: the scan's classes, objects and files
    known = {name for n in nodes if n["kind"] in ("class", "file")
             for name in _owner_names({"parent": n["id"]}, by_id)}
    classes: dict[str, list[str]] = {}   # a class's own name -> its ids (`Book`, a Scala object `Book$` too)
    subclasses: dict[str, list[str]] = {}
    split: dict[str, list[str]] = {}   # a class id without its part suffix -> every part's id
    for n in nodes:
        if n["kind"] == "class":
            split.setdefault(PART.sub("", n["id"]), []).append(n["id"])
            classes.setdefault(n["name"].rstrip("$"), []).append(n["id"])
            for sup in n.get("implements") or []:
                subclasses.setdefault(sup, []).append(n["id"])
    by_lower = {}   # `usermodel` -> the ids of class UserModel
    for name, cids in classes.items():
        by_lower.setdefault(name.lower(), []).extend(cids)

    @functools.cache
    def lineage(cid: str) -> frozenset[str]:
        """A class, every repo class it extends, every repo class extending it, and what those extend (a mixin's
        `self.save()` is the model's that a class using the mixin also extends). Cached: a deep hierarchy is
        walked once, not once per call."""
        out: set[str] = set()
        parts = split.get(PART.sub("", cid), [cid])
        for part in parts:
            out |= _ancestors(part, by_id)
        below, todo = set(parts), list(parts)   # the classes extending it, at any depth (never a base's others)
        while todo:
            for sub in subclasses.get(todo.pop(), []):
                if sub not in below:
                    below.add(sub)
                    todo.append(sub)
        for sub in below:
            out |= _ancestors(sub, by_id)
        return frozenset(out)

    def outside(m: str, held: list[str]) -> bool:
        """A method of a class unrelated to the held ones: not a top-level or extension function (its first
        parameter typed with a held class: C# `this Order o`)."""
        owner_node = by_id.get(by_id[m].get("parent") or "", {})
        if owner_node.get("kind") != "class":
            return False
        first = ((by_id[m].get("signature") or {}).get("params") or [{}])[0].get("type") or ""
        names = {by_id[c]["name"].rstrip("$") for c in held}
        return not (set(TYPE_WORD.findall(first)) & names)

    def root(nid: str) -> str | None:
        n = by_id.get(nid)
        while n is not None and n.get("parent"):
            n = by_id.get(n["parent"])
        return n["id"] if n and n["kind"] in ("service", "library") else None

    uses: dict[str, set[str]] = {}
    for r in relations:
        if r["kind"] == "uses-code":
            uses.setdefault(r["from"], set()).add(r["to"])
    # services that list one module share its code (each claiming its own packages): one call scope
    listing: dict[str, set[str]] = {}
    for n in nodes:
        if n["kind"] in ("service", "library"):
            for m in n.get("modules") or []:
                listing.setdefault(str(m).removeprefix("mod:"), set()).add(n["id"])
    peers: dict[str, set[str]] = {}
    for ids_ in listing.values():
        for x in ids_:
            peers.setdefault(x, set()).update(ids_)
    for x, ks in peers.items():
        uses[x] = set().union(uses.get(x, set()), *(uses.get(k, set()) for k in ks)) - ks
    index: dict[str, dict[str, list[str]]] = {}
    spans: dict[str, list[dict]] = {}   # file -> its methods, for the declarations around a caller
    for n in nodes:
        if n["kind"] == "method":
            spans.setdefault(n.get("file") or "", []).append(n)
            rt = root(n["id"])
            if rt:
                index.setdefault(rt, {}).setdefault(n["name"], []).append(n["id"])

    found: dict[str, dict] = {}
    dropped: dict[str, int] = {}
    for file, ff in sorted(facts.items()):
        for c in ff["calls"]:
            caller = c.get("in")
            if not caller or caller not in by_id:
                continue
            rt = root(caller)
            if not rt:
                continue
            parts = callee_parts(c["callee"])
            if not parts or LITERAL_RECEIVER.match(c["callee"]):
                continue
            name, receiver = parts[-1], (parts[-2] if len(parts) > 1 else None)
            if receiver in SELF_RECEIVERS and len(parts) == 3 and parts[0][:1].isupper():
                receiver = parts[0]    # Java `Outer.this.refresh()`: the outer class's own object
                parts = [parts[0], name]
            elif receiver is not None and receiver == c.get("self") and len(parts) == 2:
                receiver = "self"      # the method's own object under the name it gives it (Go receiver)
            elif receiver == "Self" and len(parts) == 2 and "::" in c["callee"]:
                receiver = "self"      # Rust `Self::x()` inside an `impl`: the caller's own type
            cands = [m for k in sorted(peers.get(rt, {rt})) for m in index.get(k, {}).get(name, [])]
            if not cands:
                for lib in sorted(uses.get(rt, ())):
                    cands += index.get(lib, {}).get(name, [])
            # a generated file's handler is entered through its router, never called from the app's other files
            cands = [m for m in cands if m != caller and not (by_id[m].get("generated") and by_id[m].get("file") != file)]
            # a parameter with a declared type: only its outer type's methods; a library type has none of ours
            typed = (_param_type(by_id[caller], receiver)
                     if receiver and len(parts) == 2 and receiver not in SELF_RECEIVERS else None)
            if typed is None and receiver and receiver not in SELF_RECEIVERS and receiver != "super" and (
                    len(parts) == 2 or (len(parts) == 3 and parts[0] in SELF_RECEIVERS | {c.get("self")})):
                # a field of the caller's class (`repo.save`, `this.repo.save`) typed with a repo class: as a parameter
                field = _field_type(by_id.get(by_id[caller].get("parent") or ""), receiver)
                typed = field if field is not None and any(
                    by_id[k].get("lang") == by_id[caller].get("lang") for k in classes.get(field[0], [])) else None
            if typed is not None:
                outer, refs = typed
                # the repo classes the outer type names: its resolved ref, else every class of that name in the
                # caller's language
                named = [r for r in refs if by_id.get(r, {}).get("name", "").rstrip("$") == outer] or [
                    k for k in classes.get(outer, []) if by_id[k].get("lang") == by_id[caller].get("lang")]
                if named:
                    owners = {a for r in named for a in _ancestors(r, by_id)}
                    cands = [m for m in cands if by_id[m].get("parent") in owners
                             or by_id.get(abstract.get(m, m), {}).get("parent") in owners]
                    if not cands:
                        continue   # `repo.save(...)` inherited from a framework base the scan does not hold
                elif outer not in TYPE_CONTAINERS and (refs or (len(outer) == 1 and outer.isupper())):
                    typed = None   # a container of repo types (`List[Order]`) or a type parameter: the name rules
                else:
                    continue       # `order.get(...)` on a Map: a library type has none of the repo's methods
            if scoped and any(m in scoped for m in cands):
                # a DAG's own task shadows same-named functions inside the DAG and is invisible outside it
                mine = [m for m in cands if m in scoped and receiver is None and _in_scope(by_id[caller], scoped[m])]
                cands = mine or [m for m in cands if m not in scoped]
            if not cands:
                continue
            caller_owner = by_id[caller].get("parent")
            owner = by_id.get(caller_owner or "", {})
            lang = owner.get("lang") or by_id[caller].get("lang")
            if lang in VALUE_METHODS and receiver is not None and receiver not in SELF_RECEIVERS | {"super", "?"} \
                    and not receiver[:1].isupper() and receiver not in ff.get("bound", ()) \
                    and (len(parts) == 2 or (len(parts) == 3 and parts[0] in SELF_RECEIVERS)) \
                    and (lang != "rust" or re.search(rf"\.\s*{re.escape(name)}\s*$", re.sub(r"\([^()]*\)", "", c["callee"]))):
                # `row.get(...)`: a method of a value, never a free function, which goes bare or through a name an
                # import binds (Rust `::`)
                kept = [m for m in cands if by_id.get(by_id[m].get("parent") or "", {}).get("kind") not in ("file", "package")]
                if not kept:
                    continue
                if len(kept) < len(cands) and len(cands) > MAX_CANDIDATES and len(kept) > 1:
                    # a name too common to draw before: only the class the value is named after (`recorder` ->
                    # Recorder, `validator` -> ArticleModelValidator), never a guess by arity or by elimination
                    word = receiver.lower().replace("_", "").strip("$")   # `data_source` -> DataSource
                    exact = [m for m in kept if word in {o.replace("_", "") for o in _owner_names(by_id[m], by_id)}]
                    # else whole words ending the class name (`list_state` -> InMemoryListState), three letters on
                    kept = exact or [m for m in kept if len(word) >= 3 and word in _name_tails(
                        by_id.get(by_id[m].get("parent") or "", {}).get("name", ""))]
                    if len(kept) != 1:
                        if not CHAINED.search(c["callee"]):
                            dropped[rt] = dropped.get(rt, 0) + 1
                        continue
                cands = kept
            if receiver is None and lang in NO_IMPLICIT_THIS:
                # `trim($s)`: a free function or a built-in, never another class's method
                cands = [m for m in cands if by_id.get(by_id[m].get("parent") or "", {}).get("kind") != "class"]
                if not cands:
                    continue
            if len(parts) == 3 and parts[0] in classes and parts[1][:1].islower() and typed is None \
                    and re.match(rf"\s*{re.escape(parts[0])}\s*\.\s*{re.escape(parts[1])}\s*\.", c["callee"]):
                # `Check.objects.get`: an attribute of a repo class; only its declared type's methods
                field = next((t for cid in classes[parts[0]] if (t := _field_type(by_id[cid], parts[1]))), None)
                if field is None or field[0] not in classes:
                    continue
                kin = {k for c2 in classes[field[0]] for k in lineage(c2)}
                cands = [m for m in cands if by_id[m].get("parent") in kin]
                if not cands:
                    continue
            if receiver in SELF_RECEIVERS:
                same = [m for m in cands if by_id[m].get("parent") == caller_owner]
                if not same and owner.get("kind") == "class" and owner.get("lang") not in OPEN_SELF:
                    # nothing of its own lineage: the method comes from a base the scan does not hold
                    kin = lineage(caller_owner)
                    same = [m for m in cands if by_id[m].get("parent") in kin]
                    if not same:
                        continue
                cands = same or cands
            elif receiver == "super" and name.startswith("__") and name.endswith("__"):
                continue   # super().__init__() and friends: the base class is unknown and every class has one
            elif receiver == "super":   # a base class's method: never the caller's own class
                cands = [m for m in cands if by_id[m].get("parent") != caller_owner]
                if not cands:
                    continue
            if (receiver and receiver[:1].isupper() and receiver.lower() not in known
                    and not any(receiver.lower() in _owner_names(by_id[m], by_id) for m in cands)):
                continue   # `RedisClient.create`, `Request.get`: a type the scan does not define
            if typed is None and receiver and receiver[:1].isupper() and len(parts) == 2 and receiver in classes:
                # `Book.create!`: a repo class, so only its own or its repo ancestors' methods; none means the
                # method comes from a library base class (ActiveRecord), never another class's same name
                mine = {a for c in classes[receiver] for a in _ancestors(c, by_id)}
                cands = [m for m in cands if by_id[m].get("parent") in mine]
                if not cands:
                    continue
            if typed is None and receiver and len(parts) == 2 and receiver not in SELF_RECEIVERS | {"super", "?"} \
                    and not receiver[:1].isupper() and (held := [c for c in by_lower.get(receiver.lower(), [])
                                                                 if (root(c) in peers.get(rt, {rt}) or root(c) in uses.get(rt, ()))
                                                                 and by_id[c].get("lang") not in OPEN_LINEAGE]):
                # `userModel.insert`: a value named after a repo class holds that class or one of its kin; none
                # of theirs means the method reaches it some way the scan does not follow
                kin = {k for c in held for k in lineage(c)}
                cands = [m for m in cands if by_id[m].get("parent") in kin or not outside(m, held)]
                if not cands:
                    continue
            if receiver is None and len(cands) > 1 and owner.get("kind") == "class" \
                    and (own := [m for m in cands if by_id[m].get("parent") in lineage(caller_owner)
                                 and (c.get("args") is None or _accepts(by_id[m], c["args"]))]):
                cands = own   # an implicit `this` (Java, Kotlin, C#): the caller's own lineage first
            if receiver is None and len(cands) > 1:
                # a bare name that collides means the nearest definition: the caller's own file, then package
                near = [m for m in cands if by_id[m].get("file") == file] or \
                    [m for m in cands if _package(m, by_id) == _package(caller, by_id)]
                cands = near or cands
            elif receiver not in SELF_RECEIVERS and receiver not in ("super", "?") and len(cands) > 1:
                # another object: the class its name points at, else anything but the caller's own class
                subject = _subject(receiver)
                def owner_subject(m: str) -> tuple[str, ...]:
                    return _subject(by_id.get(by_id[m].get("parent") or "", {}).get("name", ""))
                # the class the value is named after: by its name, its subject, else the one whose name ends
                # with the value's subject when only one does (`resource` -> UmsResource)
                tail = [m for m in cands if subject and subject[-1] not in GENERIC_VALUES
                        and owner_subject(m)[-len(subject):] == subject]
                named = [m for m in cands if receiver.lower() in _owner_names(by_id[m], by_id)] or \
                    [m for m in cands if subject and owner_subject(m) == subject] or \
                    (tail if len({by_id[m].get("parent") for m in tail}) == 1 else [])
                others = [m for m in cands if by_id[m].get("parent") != caller_owner]
                cands = named or others or cands
            trusted = receiver is None or receiver in SELF_RECEIVERS or typed is not None
            if not trusted and name in OBJECT_METHODS and not (receiver and (
                    receiver in classes or receiver.lower() in by_lower)):
                continue
            narrowed = False
            if not trusted and len(cands) > 1:
                # an untyped receiver: the caller's declared types may name which implementation it holds; that one
                # stays itself, folded only into a trait method that was kept too (a trace would fan out from it)
                kept = _narrowed(cands, _context_refs(by_id[caller], by_id, spans), by_id)
                narrowed, cands = len(kept) < len(cands), [m for m in kept if abstract.get(m) not in kept]
            if not narrowed:
                # an implementation and the trait method it implements are one target: the trait method
                folded = list(dict.fromkeys(abstract.get(m, m) for m in cands))
                cands = [m for m in folded if m != abstract.get(caller, caller)]
            if not cands:
                continue
            if c.get("args") is not None:   # prefer methods that can take this many arguments
                fit = [m for m in cands if _accepts(by_id[m], c["args"])]
                if not fit and not trusted and not any((receiver or "").lower() in _owner_names(by_id[m], by_id)
                                                       for m in cands):
                    continue   # `stream.run(sink)`: an unknown value whose method takes other arguments: a library's
                cands = fit or cands
            if len(cands) > MAX_CANDIDATES:
                if not CHAINED.search(c["callee"]) and parts[0] != "?":
                    dropped[rt] = dropped.get(rt, 0) + 1   # a chained result's method is a library's: no loss
                continue
            for m in cands:
                if len(cands) == 1 and (trusted or (receiver or "").lower() in _owner_names(by_id[m], by_id)):
                    conf, why = "confirmed", None
                elif narrowed:
                    conf, why = "inferred", "narrowed by the caller's declared types"
                elif len(cands) == 1:
                    conf, why = "inferred", "matched by method name only"
                else:
                    conf, why = "inferred", f"name matches {len(cands)} methods"
                rid = ids.relation_id("calls", caller, m, None)
                rel = found.get(rid)
                if rel is None:
                    rel = found[rid] = {"id": rid, "kind": "calls", "from": caller, "to": m, "key": None,
                                        "confidence": conf, "evidence": []}
                    if why:
                        rel["why"] = why
                elif conf == "confirmed" and rel["confidence"] == "inferred":
                    rel["confidence"] = "confirmed"
                    rel.pop("why", None)
                if len(rel["evidence"]) < 3:
                    rel["evidence"].append({"file": file, "line": c["line"]})
    problems = [{"text": f"{n} call site(s) in {rt} match more than {MAX_CANDIDATES} methods by name; not drawn",
                 "nodes": [rt], "source": "assemble"} for rt, n in sorted(dropped.items())]
    problems += _copy_paste(index, by_id)
    return sorted(found.values(), key=lambda r: r["id"]), problems
