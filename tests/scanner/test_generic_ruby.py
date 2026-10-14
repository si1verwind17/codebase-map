from vizcode import ids, structure
from vizcode.adapters import generic
from vizcode.adapters.langs import BY_SUFFIX, SPECS

RUBY = SPECS["ruby"]
MOD = {"id": "mod:app", "path": "app", "lang": "ruby", "build": "dir"}
FILE = "app/lib/acme/orders/repo.rb"
GOLDEN = """require "json"
require_relative "../support/base"

module Acme
  module Orders
    class Repo < Support::Base
      def initialize(db, opts = {}, *rest, key:, **kw, &blk)
        @db = db
      end

      def find(id)
        url = "http://pay.example.com/v1/#{id}/x"
        token = ENV["API_TOKEN"] || ENV.fetch("DB_URL")
        Client.new(url).get(id, *rest)
      end

      def self.build
        new(ENV.fetch "POOL")
      end

      private

      def hidden(a) = a * 2
    end

    def self.helper; end
  end
end
"""
P = "app::Acme"
ORDERS = f"{P}.Orders"
REPO = f"{ORDERS}.Repo"


def parse(src: str, rel: str = FILE):
    return generic.parse(src.encode(), rel, MOD, ids.IdRegistry(), spec=RUBY)


def test_ruby_spec_registered():
    assert BY_SUFFIX[".rb"] is RUBY
    assert RUBY.grammar == "ruby" and RUBY.sep == "/"
    assert structure.LANGS[".rb"][0] == "ruby"


def test_ruby_nodes():
    res = parse(GOLDEN)
    # the outermost module names the package and is not a class itself
    assert res["package"] == "Acme"
    assert res["parse_error"] is False
    got = [(n["id"], n["kind"], n["name"], n["parent"], n["line"], n["visibility"]) for n in res["nodes"]]
    assert got == [
        (ORDERS, "class", "Orders", f"{P}/", 5, "public"),
        (REPO, "class", "Repo", ORDERS, 6, "public"),
        (f"{REPO}#initialize/5", "method", "initialize", REPO, 7, "public"),
        (f"{REPO}#find/1", "method", "find", REPO, 11, "public"),
        (f"{REPO}#build/0", "method", "build", REPO, 17, "public"),
        # after a bare `private` in the class body
        (f"{REPO}#hidden/1", "method", "hidden", REPO, 23, "private"),
        (f"{ORDERS}#helper/0", "method", "helper", ORDERS, 26, "public"),
    ]
    n = {x["id"]: x for x in res["nodes"]}
    # a block parameter is not counted; splats take any count
    assert n[f"{REPO}#initialize/5"]["signature"] == {
        "params": [{"name": "db", "type": None}, {"name": "opts", "type": None}, {"name": "*rest", "type": None},
                   {"name": "key", "type": None}, {"name": "*kw", "type": None}],
        "returns": None}
    assert res["supers"] == [(REPO, ["Support::Base"])]


def test_ruby_facts():
    res = parse(GOLDEN)
    # require/require_relative are imports, not calls
    assert res["imports"] == [
        {"target": "json", "line": 1, "relative": False, "names": []},
        {"target": "../support/base", "line": 2, "relative": True, "names": []},
    ]
    find, build = f"{REPO}#find/1", f"{REPO}#build/0"
    assert res["calls"] == [
        {"callee": "ENV.fetch", "in": find, "line": 13, "args": 1},
        {"callee": "Client.new(url).get", "in": find, "line": 14, "args": None},
        {"callee": "Client.new", "in": find, "line": 14, "args": 1},
        {"callee": "new", "in": build, "line": 18, "args": 1},
        {"callee": "ENV.fetch", "in": build, "line": 18, "args": 1},
    ]
    assert res["strings"] == [
        {"text": "http://pay.example.com/v1/{id}/x", "line": 12, "in": find},
        {"text": "API_TOKEN", "line": 13, "in": find},
        {"text": "DB_URL", "line": 13, "in": find},
        {"text": "POOL", "line": 18, "in": build},
    ]
    assert res["env_keys"] == [{"key": "API_TOKEN", "line": 13}, {"key": "DB_URL", "line": 13},
                               {"key": "POOL", "line": 18}]


def test_ruby_without_module_package_is_the_folder():
    src = 'class Order < ApplicationRecord\n  def q\n    sql = <<~SQL\n      SELECT #{x}\n    SQL\n  end\nend\n'
    res = parse(src, "app/models/order.rb")
    assert res["package"] == "models"
    assert [n["id"] for n in res["nodes"]] == ["app::models.Order", "app::models.Order#q/0"]
    # a heredoc body as written, from the end of the `<<~SQL` line to the closing word
    assert res["strings"] == [{"text": "\n      SELECT {x}\n    ", "line": 3, "in": "app::models.Order#q/0"}]


def test_ruby_non_ascii():
    res = parse('def grüße(name)\n  "Grüße, #{name}"\nend\n', "app/g.rb")
    assert [n["id"] for n in res["nodes"]] == ["app::_root_/g.rb", "app::_root_/g.rb#grüße/1"]
    assert res["strings"] == [{"text": "Grüße, {name}", "line": 2, "in": "app::_root_/g.rb#grüße/1"}]


def test_ruby_survives_broken_file():
    src = "class Ok\n  def fine\n    go(1)\n  end\nend\n\nclass Broken\n  def half(x\n    call(\n"
    res = parse(src, "app/b.rb")
    assert res["parse_error"] is True
    assert [n["id"] for n in res["nodes"]][:2] == ["app::Ok", "app::Ok#fine/0"]
    assert {"callee": "go", "in": "app::Ok#fine/0", "line": 3, "args": 1} in res["calls"]


def test_ruby_end_to_end(make_repo):
    repo = make_repo({"app/lib/acme/orders/repo.rb": GOLDEN})
    s = structure.build(repo)
    f = "app/lib/acme/orders/repo.rb"
    assert s["files"][f]["lang"] == "ruby"
    assert [e["key"] for e in s["facts"][f]["env_keys"]] == ["API_TOKEN", "DB_URL", "POOL"]


def test_ruby_scoped_module_package_uses_dots():
    """`module A::B` names package A.B: ids already use `::` between module and package."""
    res = parse("module Acme::Orders\n  class Repo\n  end\nend\n")
    assert res["package"] == "Acme.Orders"
    assert [n["id"] for n in res["nodes"]] == ["app::Acme.Orders.Repo"]
