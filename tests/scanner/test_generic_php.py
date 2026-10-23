from vizcode import ids, structure
from vizcode.adapters import generic
from vizcode.adapters.langs import BY_SUFFIX, SPECS

PHP = SPECS["php"]
MOD = {"id": "mod:web", "path": "web", "lang": "php", "build": "dir"}
FILE = "web/src/Http/OrdersController.php"
GOLDEN = r"""<?php
namespace App\Http;

use App\Models\Order;
use Illuminate\Support\{Str, Arr as A};

#[Route('/orders')]
final class OrdersController extends Controller implements HasRoutes, \Psr\Log\LoggerAware
{
    use Traits\Logs;

    public function __construct(private Repo $repo, string ...$tags) {}

    #[Get('/{id}')]
    public function show(string $id, $full = false): ?Order
    {
        $url = "http://pay.example.com/v1/{$id}/$full";
        $key = getenv('API_KEY') ?: $_ENV['DB_URL'] ?? env('APP_KEY');
        return $this->repo->find($id, ...$this->tags) ?? Order::make(new Client($url));
    }

    private function sql(): string
    {
        return <<<SQL
        SELECT * FROM orders WHERE id = $id
        SQL;
    }

    function plain() {}
}

interface HasRoutes { function routes(): array; }
trait Logs {}

function helper($x) { return strlen($x); }
"""
P = "web::App\\Http"
CTRL = f"{P}.OrdersController"
FILE_ID = f"{P}/OrdersController.php"


def parse(src: str, rel: str = FILE):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=PHP)


def test_php_spec_registered():
    assert BY_SUFFIX[".php"] is PHP
    assert PHP.grammar == "php" and PHP.sep == "\\"
    assert structure.LANGS[".php"][0] == "php"


def test_php_nodes():
    res = parse(GOLDEN)
    assert res["package"] == "App\\Http"
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        (CTRL, "class", "OrdersController", f"{P}/", 7, "public"),
        (f"{CTRL}#__construct/2", "method", "__construct", CTRL, 12, "public"),
        (f"{CTRL}#show/2", "method", "show", CTRL, 14, "public"),
        (f"{CTRL}#sql/0", "method", "sql", CTRL, 22, "private"),
        # no modifier: public in PHP
        (f"{CTRL}#plain/0", "method", "plain", CTRL, 29, "public"),
        (f"{P}.HasRoutes", "class", "HasRoutes", f"{P}/", 32, "public"),
        (f"{P}.HasRoutes#routes/0", "method", "routes", f"{P}.HasRoutes", 32, "public"),
        (f"{P}.Logs", "class", "Logs", f"{P}/", 33, "public"),
        (FILE_ID, "file", "OrdersController.php", f"{P}/", 1, "public"),
        (f"{FILE_ID}#helper/1", "method", "helper", FILE_ID, 35, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    assert n[f"{CTRL}#__construct/2"]["signature"] == {
        "params": [{"name": "repo", "type": "Repo"}, {"name": "*tags", "type": "string"}], "returns": None}
    assert n[f"{CTRL}#show/2"]["signature"] == {
        "params": [{"name": "id", "type": "string"}, {"name": "full", "type": None}], "returns": "?Order"}
    assert n[f"{P}.HasRoutes#routes/0"]["signature"]["returns"] == "array"
    assert res["supers"] == [(CTRL, ["Controller", "HasRoutes", "\\Psr\\Log\\LoggerAware", "Traits\\Logs"])]


def test_php_facts():
    res = parse(GOLDEN)
    assert res["imports"] == [
        {"target": "App\\Models", "line": 4, "relative": False, "names": ["Order"]},
        {"target": "Illuminate\\Support", "line": 5, "relative": False, "names": ["Str", "Arr"]},
    ]
    show = f"{CTRL}#show/2"
    assert res["calls"] == [
        {"callee": "getenv", "in": show, "line": 18, "args": 1},
        {"callee": "env", "in": show, "line": 18, "args": 1},
        # `...$this->tags` hides the count
        {"callee": "$this->repo->find", "in": show, "line": 19, "args": None},
        {"callee": "Order::make", "in": show, "line": 19, "args": 1},
        {"callee": "Client", "in": show, "line": 19, "args": 1},
        {"callee": "strlen", "in": f"{FILE_ID}#helper/1", "line": 35, "args": 1},
    ]
    assert res["strings"] == [
        {"text": "/orders", "line": 7, "in": None},
        {"text": "/{id}", "line": 14, "in": show},
        {"text": "http://pay.example.com/v1/{id}/{full}", "line": 17, "in": show},
        {"text": "API_KEY", "line": 18, "in": show},
        {"text": "DB_URL", "line": 18, "in": show},
        {"text": "APP_KEY", "line": 18, "in": show},
        # a heredoc body as written, from the end of the `<<<SQL` line
        {"text": "\n        SELECT * FROM orders WHERE id = {id}", "line": 24, "in": f"{CTRL}#sql/0"},
    ]
    assert res["env_keys"] == [{"key": "API_KEY", "line": 18}, {"key": "DB_URL", "line": 18},
                               {"key": "APP_KEY", "line": 18}]
    assert res["annotations"] == [
        {"node": CTRL, "text": "#[Route('/orders')]", "line": 7},
        {"node": show, "text": "#[Get('/{id}')]", "line": 14},
    ]


def test_php_without_namespace_package_is_the_folder():
    res = parse("<?php\nclass Café { function grüße() { return 'Größe'; } }\n", "web/lib/k.php")
    assert res["package"] == "lib"
    assert [n["id"] for n in res["nodes"]] == ["web::lib.Café", "web::lib.Café#grüße/0"]
    assert res["strings"] == [{"text": "Größe", "line": 2, "in": "web::lib.Café#grüße/0"}]


def test_php_survives_broken_file():
    src = "<?php\nnamespace A;\nclass Ok { function fine() { go(); } }\nclass Broken {\n  function half($x) {\n    call(\n"
    res = parse(src, "web/b.php")
    assert res["parse_error"] is True
    assert [n["id"] for n in res["nodes"]][:2] == ["web::A.Ok", "web::A.Ok#fine/0"]
    assert {"callee": "go", "in": "web::A.Ok#fine/0", "line": 3, "args": 0} in res["calls"]


def test_php_end_to_end(make_repo):
    repo = make_repo({"web/src/Http/OrdersController.php": GOLDEN})
    s = structure.build(repo)
    f = "web/src/Http/OrdersController.php"
    assert s["files"][f]["lang"] == "php"
    assert [e["key"] for e in s["facts"][f]["env_keys"]] == ["API_KEY", "DB_URL", "APP_KEY"]


def test_php_traits_a_class_uses_are_supers():
    res = parse("<?php\nnamespace App;\n\nclass A extends B {\n    use Logs, \\App\\Concerns\\Audits;\n"
                "    use Caches { get as cached; }\n    function f() {}\n}\n")
    assert res["supers"] == [("web::App.A", ["B", "Logs", "\\App\\Concerns\\Audits", "Caches"])]
