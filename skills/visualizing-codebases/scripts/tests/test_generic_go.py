from vizcode import ids, structure
from vizcode.adapters import generic
from vizcode.adapters.langs import BY_SUFFIX, SPECS

GO = SPECS["go"]
MOD = {"id": "mod:svc", "path": "svc", "lang": "go", "build": "dir"}
FILE = "svc/internal/orders/repo.go"
GOLDEN = """package orders

import (
	"fmt"
	log "github.com/sirupsen/logrus"
	"os"
)

// Repo stores orders.
type Repo struct {
	db *sql.DB
}

type Store interface {
	Find(id string) (*Order, error)
	count() int
}

func (r *Repo) Find(id string, a, b int, rest ...string) (*Order, error) {
	q := `SELECT * FROM orders WHERE id = $1`
	log.Info("find " + id)
	return nil, fmt.Errorf("x %s", os.Getenv("DB_URL"))
}

func (r Repo) count() int { return len(r.items(xs...)) }

func New(db *sql.DB) *Repo { return &Repo{db: db} }
"""
P = "svc::internal/orders"
REPO = f"{P}.Repo"
FILE_ID = f"{P}/repo.go"


def parse(src: str, rel: str = FILE):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=GO)


def test_go_spec_registered():
    assert BY_SUFFIX[".go"] is GO
    assert GO.grammar == "go" and GO.package == "dir" and GO.sep == "/"
    assert structure.LANGS[".go"][0] == "go"


def test_go_nodes():
    res = parse(GOLDEN)
    # the package is the folder relative to the module; the declared name matches its last segment
    assert res["package"] == "internal/orders"
    assert "package_declared" not in res
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        (REPO, "class", "Repo", f"{P}/", 10, "public"),
        (f"{P}.Store", "class", "Store", f"{P}/", 14, "public"),
        (f"{P}.Store#Find/1", "method", "Find", f"{P}.Store", 15, "public"),
        # a lower-case name is unexported
        (f"{P}.Store#count/0", "method", "count", f"{P}.Store", 16, "private"),
        # pointer and value receivers attach to the type's class node; `a, b int` is two parameters
        (f"{REPO}#Find/4", "method", "Find", REPO, 19, "public"),
        (f"{REPO}#count/0", "method", "count", REPO, 25, "private"),
        (FILE_ID, "file", "repo.go", f"{P}/", 1, "public"),
        (f"{FILE_ID}#New/1", "method", "New", FILE_ID, 27, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    assert n[REPO]["metrics"]["methods"] == 2
    assert n[f"{REPO}#Find/4"]["signature"] == {
        "params": [{"name": "id", "type": "string"}, {"name": "a", "type": "int"}, {"name": "b", "type": "int"},
                   {"name": "*rest", "type": "string"}],
        "returns": "(*Order, error)"}
    assert n[f"{REPO}#count/0"]["signature"] == {"params": [], "returns": "int"}
    assert n[f"{FILE_ID}#New/1"]["signature"] == {"params": [{"name": "db", "type": "*sql.DB"}], "returns": "*Repo"}
    assert res["supers"] == []
    assert res["attached"] == []


def test_go_facts():
    res = parse(GOLDEN)
    assert res["imports"] == [
        {"target": "fmt", "line": 4, "relative": False, "names": []},
        {"target": "github.com/sirupsen/logrus", "line": 5, "relative": False, "names": [], "as": "log"},
        {"target": "os", "line": 6, "relative": False, "names": []},
    ]
    find, count = f"{REPO}#Find/4", f"{REPO}#count/0"
    assert res["calls"] == [
        {"callee": "log.Info", "in": find, "line": 21, "args": 1},
        {"callee": "fmt.Errorf", "in": find, "line": 22, "args": 2},
        {"callee": "os.Getenv", "in": find, "line": 22, "args": 1},
        {"callee": "len", "in": count, "line": 25, "args": 1},
        # `xs...` hides the count
        {"callee": "r.items", "in": count, "line": 25, "args": None, "self": "r"},   # the receiver
    ]
    assert res["strings"] == [
        {"text": "SELECT * FROM orders WHERE id = $1", "line": 20, "in": find},
        {"text": "find ", "line": 21, "in": find},
        {"text": "x %s", "line": 22, "in": find},
        {"text": "DB_URL", "line": 22, "in": find},
    ]
    assert res["env_keys"] == [{"key": "DB_URL", "line": 22}]
    assert res["annotations"] == []


def test_go_declared_package_mismatch_is_recorded():
    res = parse("package order\n\nfunc F() {}\n")
    assert res["package"] == "internal/orders"
    assert res["package_declared"] == "order"


def test_go_methods_on_a_type_of_another_file_wait_for_the_structure_pass():
    res = parse("package orders\n\nfunc (r *Repo) Save() error { return nil }\n", "svc/internal/orders/save.go")
    assert [(n["id"], n["parent"]) for n in res["nodes"]] == [(f"{REPO}#Save/0", REPO)]
    assert [(a["id"], a["kind"], a["name"], a["metrics"]["methods"]) for a in res["attached"]] == [
        (REPO, "class", "Repo", 1)]


def test_go_non_ascii():
    res = parse('package orders\n\nfunc Grüße(name string) string { return "Grüße, " + name }\n',
                "svc/internal/orders/g.go")
    assert [n["id"] for n in res["nodes"]] == [f"{P}/g.go", f"{P}/g.go#Grüße/1"]
    assert res["strings"] == [{"text": "Grüße, ", "line": 3, "in": f"{P}/g.go#Grüße/1"}]


def test_go_survives_broken_file():
    src = "package orders\n\nfunc Fine() { go1() }\n\nfunc Half(x int) {\n\tcall(\n"
    res = parse(src, "svc/internal/orders/b.go")
    assert res["parse_error"] is True
    assert f"{P}/b.go#Fine/0" in [n["id"] for n in res["nodes"]]
    assert {"callee": "go1", "in": f"{P}/b.go#Fine/0", "line": 3, "args": 0} in res["calls"]


def test_go_end_to_end_methods_join_across_files(make_repo):
    """Methods in several files of one package join the type's one class node; a receiver type no file
    declares gets a class node of its own."""
    repo = make_repo({"svc/orders/repo.go": "package orders\n\ntype Repo struct{}\n\nfunc (r Repo) A() {}\n",
                      "svc/orders/save.go": "package orders\n\nfunc (r *Repo) B(x int) {}\n"
                                            "func (h Hidden) C() {}\n"})
    s = structure.build(repo)
    assert s["files"]["svc/orders/save.go"]["lang"] == "go"
    classes = {n["id"]: n for n in s["nodes"] if n["kind"] == "class"}
    repo_id = next(i for i, n in classes.items() if n["name"] == "Repo")
    assert [i for i in classes if i.startswith(repo_id)] == [repo_id]          # one class, no `~2`
    assert classes[repo_id]["metrics"]["methods"] == 2
    assert sorted(n["name"] for n in s["nodes"] if n.get("parent") == repo_id) == ["A", "B"]
    hidden = next(n for n in classes.values() if n["name"] == "Hidden")
    assert hidden["file"] == "svc/orders/save.go" and hidden["metrics"]["methods"] == 1
    assert [n["name"] for n in s["nodes"] if n.get("parent") == hidden["id"]] == ["C"]


def test_go_exported_is_any_unicode_upper_case_first_letter():
    res = parse("package orders\n\nfunc Δelta() {}\nfunc δelta() {}\nfunc Ärger() {}\nfunc _x() {}\n")
    assert [(n["name"], n["visibility"]) for n in res["nodes"] if n["kind"] == "method"] == [
        ("Δelta", "public"), ("δelta", "private"), ("Ärger", "public"), ("_x", "private")]
