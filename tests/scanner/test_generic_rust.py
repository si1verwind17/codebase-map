from vizcode import ids, structure
from vizcode.adapters import generic
from vizcode.adapters.langs import BY_SUFFIX, SPECS

RUST = SPECS["rust"]
MOD = {"id": "mod:core", "path": "core", "lang": "rust", "build": "dir"}
FILE = "core/src/orders/repo.rs"
GOLDEN = """mod db;
use crate::db::{Pool, Conn as C};
use std::env;
use super::model::*;

#[derive(Debug, Clone)]
pub struct Repo<T> {
    pool: T,
}

pub trait Store: Send + Sync {
    fn find(&self, id: &str) -> Option<Order>;
}

impl<T> Repo<T> {
    pub fn new(pool: T) -> Self {
        Repo { pool }
    }

    fn url(&self, (a, b): (u32, u32)) -> String {
        format!("http://pay.example.com/v1/{}/{}", a, b)
    }
}

impl<T> Store for Repo<T> {
    fn find(&self, id: &str) -> Option<Order> {
        let url = std::env::var("DB_URL").ok()?;
        let n = id.parse::<u32>().ok();
        self.query(r#"SELECT * FROM orders"#, n)
    }
}

pub fn handler(repo: &Repo<Pool>, mut id: String) -> String {
    repo.find(&id).map(|o| o.id).unwrap_or_default()
}
"""
P = "core::src/orders"
REPO = f"{P}.repo.Repo"
STORE = f"{P}.repo.Store"
FILE_ID = f"{P}/repo.rs"


def parse(src: str, rel: str = FILE):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=RUST)


def test_rust_spec_registered():
    assert BY_SUFFIX[".rs"] is RUST
    assert RUST.grammar == "rust" and RUST.package == "dir" and RUST.sep == "::"
    assert structure.LANGS[".rs"][0] == "rust"


def test_rust_nodes():
    res = parse(GOLDEN)
    assert res["package"] == "src/orders"
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        # the attribute before the struct opens its span
        (REPO, "class", "Repo", f"{P}/", 6, "public"),
        (STORE, "class", "Store", f"{P}/", 11, "public"),
        # a trait's functions are public whatever is written
        (f"{STORE}#find/1", "method", "find", STORE, 12, "public"),
        # both impl blocks join the struct's one class node; `&self` is not a parameter
        (f"{REPO}#new/1", "method", "new", REPO, 16, "public"),
        (f"{REPO}#url/1", "method", "url", REPO, 20, "private"),
        # a trait impl's functions are public too
        (f"{REPO}#find/1", "method", "find", REPO, 26, "public"),
        (FILE_ID, "file", "repo.rs", f"{P}/", 1, "public"),
        (f"{FILE_ID}#handler/2", "method", "handler", FILE_ID, 33, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    assert n[REPO]["metrics"]["methods"] == 3
    assert n[f"{REPO}#new/1"]["signature"] == {"params": [{"name": "pool", "type": "T"}], "returns": "Self"}
    assert n[f"{REPO}#url/1"]["signature"] == {"params": [{"name": "a", "type": "(u32, u32)"}],
                                               "returns": "String"}
    assert n[f"{FILE_ID}#handler/2"]["signature"] == {
        "params": [{"name": "repo", "type": "&Repo<Pool>"}, {"name": "id", "type": "String"}], "returns": "String"}
    # a trait's bounds, and the trait an impl block implements for its type
    assert res["supers"] == [(STORE, ["Send", "Sync"]), (REPO, ["Store"])]
    assert res["attached"] == []
    assert res["annotations"] == [{"node": REPO, "text": "#[derive(Debug, Clone)]", "line": 6}]


def test_rust_facts():
    res = parse(GOLDEN)
    assert res["imports"] == [
        # `mod db;` names a file of this crate
        {"target": "db", "line": 1, "relative": True, "names": []},
        {"target": "crate::db::Pool", "line": 2, "relative": True, "names": []},
        {"target": "crate::db::Conn", "line": 2, "relative": True, "names": [], "renames": {"C": "Conn"}},
        {"target": "std::env", "line": 3, "relative": False, "names": []},
        {"target": "super::model", "line": 4, "relative": True, "names": []},
    ]
    find, handler = f"{REPO}#find/1", f"{FILE_ID}#handler/2"
    # macros (`format!`) are not calls; a turbofish is left out of the callee
    assert res["calls"] == [
        {"callee": 'std::env::var("DB_URL").ok', "in": find, "line": 27, "args": 0},
        {"callee": "std::env::var", "in": find, "line": 27, "args": 1},
        {"callee": "id.parse().ok", "in": find, "line": 28, "args": 0},
        {"callee": "id.parse", "in": find, "line": 28, "args": 0},
        {"callee": "self.query", "in": find, "line": 29, "args": 2},
        {"callee": "repo.find(&id).map(|o| o.id).unwrap_or_default", "in": handler, "line": 34, "args": 0},
        {"callee": "repo.find(&id).map", "in": handler, "line": 34, "args": 1},
        {"callee": "repo.find", "in": handler, "line": 34, "args": 1},
    ]
    assert res["strings"] == [
        {"text": "http://pay.example.com/v1/{}/{}", "line": 21, "in": f"{REPO}#url/1"},
        {"text": "DB_URL", "line": 27, "in": find},
        {"text": "SELECT * FROM orders", "line": 29, "in": find},
    ]
    assert res["env_keys"] == [{"key": "DB_URL", "line": 27}]


def test_rust_inline_module_and_foreign_impl():
    src = ("mod inner {\n    pub fn f() {}\n}\n"
           "impl From<u8> for crate::other::Thing {\n    fn from(x: u8) -> Self { todo!() }\n}\n")
    res = parse(src, "core/src/lib.rs")
    pkg = "core::src"
    assert [(n["id"], n["parent"]) for n in res["nodes"]] == [
        (f"{pkg}.lib.inner", f"{pkg}/"), (f"{pkg}.lib.inner#f/0", f"{pkg}.lib.inner"),
        (f"{pkg}.lib.Thing#from/1", f"{pkg}.lib.Thing")]
    # the impl's type is declared elsewhere: a class node is made for it after the walk (structure pass)
    assert [(a["id"], a["line"], a["metrics"]["methods"]) for a in res["attached"]] == [(f"{pkg}.lib.Thing", 4, 1)]
    assert res["supers"] == [(f"{pkg}.lib.Thing", ["From"])]
    assert res["imports"] == []


def test_rust_non_ascii():
    res = parse('fn grüße(name: &str) -> String { format!("Grüße, {name}") }\n', "core/src/g.rs")
    assert [n["id"] for n in res["nodes"]] == ["core::src/g.rs", "core::src/g.rs#grüße/1"]
    assert res["strings"] == [{"text": "Grüße, {name}", "line": 1, "in": "core::src/g.rs#grüße/1"}]


def test_rust_survives_broken_file():
    src = "fn fine() { go(); }\n\nfn half(x: i32) {\n    call(\n"
    res = parse(src, "core/src/b.rs")
    assert res["parse_error"] is True
    assert "core::src/b.rs#fine/0" in [n["id"] for n in res["nodes"]]
    assert {"callee": "go", "in": "core::src/b.rs#fine/0", "line": 1, "args": 0} in res["calls"]


def test_rust_end_to_end(make_repo):
    repo = make_repo({"core/src/orders/repo.rs": GOLDEN})
    s = structure.build(repo)
    f = "core/src/orders/repo.rs"
    assert s["files"][f]["lang"] == "rust"
    assert [e["key"] for e in s["facts"][f]["env_keys"]] == ["DB_URL"]
    store = next(n for n in s["nodes"] if n["kind"] == "class" and n["name"] == "Store")
    repo_node = next(n for n in s["nodes"] if n["kind"] == "class" and n["name"] == "Repo")
    assert repo_node["implements"] == [store["id"]]


def test_rust_impl_of_an_unnamed_type_attaches_to_the_file():
    """A blanket impl (`for T`, a type parameter), a tuple, or a reference to those creates no class."""
    src = ("impl<T: Display> Show for T {\n    fn a(&self) {}\n}\n"
           "impl<'a, T> Show for &'a T {\n    fn b(&self) {}\n}\n"
           "impl Show for (A, B) {\n    fn c(&self) {}\n}\n"
           "impl<T> Show for Wrapper<T> {\n    fn d(&self) {}\n}\n"
           "impl Show for &Named {\n    fn e(&self) {}\n}\n")
    res = parse(src)
    assert [(n["id"], n["parent"]) for n in res["nodes"]] == [
        (FILE_ID, f"{P}/"), (f"{FILE_ID}#a/0", FILE_ID), (f"{FILE_ID}#b/0", FILE_ID), (f"{FILE_ID}#c/0", FILE_ID),
        (f"{P}.repo.Wrapper#d/0", f"{P}.repo.Wrapper"), (f"{P}.repo.Named#e/0", f"{P}.repo.Named")]
    assert sorted(a["name"] for a in res["attached"]) == ["Named", "Wrapper"]


def test_rust_cfg_test_items_are_left_out():
    """`#[cfg(test)]` marks test-only code inside a source file: the item under it (a `mod tests`, a function) is
    neither a node nor a source of imports, calls or strings."""
    r = parse("use crate::db::Pool;\n\npub fn place() -> u32 { 1 }\n\n#[cfg(test)]\n// unit tests\nmod tests {\n"
              "    use claims::assert_ok;\n    #[test]\n    fn places() { super::place(); assert_ok!(\"x\"); }\n}\n\n"
              "#[cfg(test)]\nfn fixture() -> u32 { place() }\n")
    assert [n["name"] for n in r["nodes"]] == ["repo.rs", "place"]
    assert [i["target"] for i in r["imports"]] == ["crate::db::Pool"]
    assert r["calls"] == [] and r["strings"] == []


def test_rust_impl_in_another_file_joins_the_declared_struct(make_repo):
    # `impl Handler<A> for Executor` in a submodule: methods of the struct `db/mod.rs` declares, no class per file
    s = structure.build(make_repo({
        "Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\n',
        "src/main.rs": "mod db;\nfn main() {}\n",
        "src/db/mod.rs": "mod users;\npub struct Executor { pub pool: u8 }\n",
        "src/db/users.rs": "use super::Executor;\npub struct A;\npub struct B;\n"
                           "impl Handler<A> for Executor {\n    fn handle(&mut self, m: A, c: &mut u8) -> u8 { 0 }\n}\n"
                           "impl Handler<B> for Executor {\n    fn handle(&mut self, m: B, c: &mut u8) -> u8 { self.run() }\n}\n"
                           "impl Executor {\n    fn run(&self) -> u8 { 1 }\n}\n",
    }), "docs/viz-code")
    execs = [n for n in s["nodes"] if n["kind"] == "class" and n["name"] == "Executor"]
    assert [n["file"] for n in execs] == ["src/db/mod.rs"]
    methods = sorted(n["id"] for n in s["nodes"] if n["kind"] == "method" and n.get("parent") == execs[0]["id"])
    assert methods == [execs[0]["id"] + m for m in ("#handle/2", "#handle/2~2", "#run/0")]
    calls = [c for c in s["facts"]["src/db/users.rs"]["calls"] if c["callee"] == "self.run"]
    assert [c["in"] for c in calls] == [execs[0]["id"] + "#handle/2~2"]


def test_rust_impl_joins_the_struct_its_use_names_and_keeps_ids_per_file(make_repo):
    # two `Record`s: the impl's `use` names db::model's; a type no `use` names keeps its own class; a method two
    # files give the struct carries its file's name, so one file's impls never renumber another's
    s = structure.build(make_repo({
        "Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\n',
        "src/main.rs": "mod model;\nmod db;\nmod api;\nfn main() {}\n",
        "src/model.rs": "pub struct Record;\n",
        "src/db/mod.rs": "pub mod model;\npub mod a;\npub mod b;\npub struct Exec;\n",
        "src/db/model.rs": "pub struct Record;\n",
        "src/api/conv.rs": "use crate::db::model::Record;\nimpl Record {\n    fn to_json(&self) -> u8 { 0 }\n}\n"
                           "impl Related for Entity {\n    fn to() -> u8 { 0 }\n}\n",
        "src/db/a.rs": "use super::Exec;\nimpl Handler<A> for Exec {\n    fn handle(&mut self, m: A) -> u8 { 0 }\n}\n",
        "src/db/b.rs": "use super::*;\nimpl Handler<B> for Exec {\n    fn handle(&mut self, m: B) -> u8 { 0 }\n}\n",
    }), "docs/viz-code")
    methods = {n["id"].split("::", 1)[1] for n in s["nodes"] if n["kind"] == "method"}
    assert "src/db.model.Record#to_json/0" in methods
    assert "src/api.conv.Entity#to/0" in methods
    assert {"src/db.mod.Exec#handle/1~a", "src/db.mod.Exec#handle/1~b"} <= methods


def test_rust_impl_follows_a_pub_use_and_an_unprefixed_use(make_repo):
    s = structure.build(make_repo({
        "Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\n',
        "src/main.rs": "mod db;\nmod api;\nmod settings;\nfn main() {}\n",
        "src/db/mod.rs": "mod model;\npub use self::model::Record;\n",
        "src/db/model.rs": "pub struct Record;\n",
        "src/api/conv.rs": "use crate::db::Record;\nimpl Record {\n    fn to_json(&self) -> u8 { 0 }\n}\n",
        "src/settings/mod.rs": "mod structs;\nuse structs::Settings;\nimpl Settings {\n    fn init() -> u8 { 0 }\n}\n",
        "src/settings/structs.rs": "pub struct Settings;\n",
    }), "docs/viz-code")
    methods = {n["id"].split("::", 1)[1] for n in s["nodes"] if n["kind"] == "method"}
    assert {"src/db.model.Record#to_json/0", "src/settings.structs.Settings#init/0"} <= methods


def test_rust_impl_through_a_glob_cycle_joins_the_struct(make_repo):
    # db/mod.rs and db/models.rs glob each other: the lookup from models.rs still finds schema's X
    s = structure.build(make_repo({
        "Cargo.toml": '[package]\nname = "app"\nversion = "0.1.0"\n',
        "src/main.rs": "mod schema;\nmod db;\nfn main() {}\n",
        "src/schema.rs": "pub struct X;\n",
        "src/db/mod.rs": "mod models;\nuse crate::schema::*;\npub use self::models::*;\n"
                         "impl Show for X {\n    fn show(&self) -> u8 { 0 }\n}\n",
        "src/db/models.rs": "use super::*;\nimpl Load for X {\n    fn load(&self) -> u8 { 0 }\n}\n",
    }), "docs/viz-code")
    methods = {n["id"].split("::", 1)[1] for n in s["nodes"] if n["kind"] == "method"}
    assert {"src.schema.X#show/0", "src.schema.X#load/0"} <= methods
