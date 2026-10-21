import json

import extract
from conftest import commit_all, write_files

from vizcode import structure


def test_build_structure(shop_repo):
    s = structure.build(shop_repo, "docs/viz-code")
    files = set(s["files"])
    assert "tests/test_x.py" not in files and "docs/screen.py" not in files
    assert not any("src/test" in f for f in files)
    assert {m["id"] for m in s["modules"]} == {"mod:common", "mod:shop", "mod:worker", "mod:pylib", "mod:scripts"}
    pkgs = {n["id"]: n for n in s["nodes"] if n["kind"] == "package"}
    assert pkgs["shop::io.demo.shop.api/"]["parent"] == "mod:shop"
    routes = {(r["method"], r["path"]): r["handler"] for r in s["facts"]["shop/src/main/scala/io/demo/shop/api/OrderApi.scala"]["routes"]}
    assert routes == {("POST", "/v1/orders/create"): "shop::io.demo.shop.api.OrderApi$#createEndpoint/0",
                      ("GET", "/v1/orders/{id}"): "shop::io.demo.shop.api.OrderApi$#getEndpoint/0"}
    uses = {(r["from"], r["to"]) for r in s["relations"]}
    assert uses == {("mod:shop", "mod:common"), ("mod:pylib", "mod:worker")}  # relative import stays inside worker
    sql = s["facts"]["worker/main.py"]["sql"]
    assert {"verb": "insert", "reads": [], "writes": ["public.jobs"]} in [{k: q[k] for k in ("verb", "reads", "writes")} for q in sql]
    assert [x["lib"] for x in s["facts"]["scripts/run_once.py"]["sinks"]] == ["psycopg"]
    assert s["files"]["worker/main.py"]["node"] == "worker::worker.main"
    assert s["stats"]["parse_errors"] == 0


def test_uncommitted_and_oversized_files(shop_repo):
    write_files(shop_repo, {"worker/big.py": "x = 1\n" * 100_000})
    commit_all(shop_repo)
    (shop_repo / "worker" / "dirty.py").write_text("def dirty():\n    pass\n")
    s = structure.build(shop_repo, "docs/viz-code")
    assert "worker/dirty.py" not in s["files"]
    assert s["skipped"] == [{"file": "worker/big.py", "reason": "larger than 524288 bytes"}]


def test_output_dir_is_never_scanned(shop_repo):
    write_files(shop_repo, {"docs/viz-code/leftover.py": "def x():\n    pass\n",
                            "out/map/leftover.py": "def y():\n    pass\n"})
    commit_all(shop_repo)
    s = structure.build(shop_repo, "out/map")
    assert "out/map/leftover.py" not in s["files"]


def test_extract_cli(shop_repo, capsys):
    assert extract.main([str(shop_repo)]) == 0
    out = shop_repo / "docs" / "viz-code"
    s = json.loads((out / "structure.json").read_text())
    assert s["meta"]["commit"] == json.loads(capsys.readouterr().out)["commit"]
    summary = (out / "summary.md").read_text()
    assert "POST /v1/orders/create" in summary and "uses-code:** mod:common" in summary


def test_extract_cli_not_a_repo(tmp_path, capsys):
    assert extract.main([str(tmp_path)]) == 2
    assert "error:" in capsys.readouterr().err


def test_exclude_flags_are_kept_in_stack_yaml_for_the_next_run(shop_repo):
    # `--exclude` adds its globs to stack.yaml's `exclude` list (once each): a rescan without the flag reuses them
    assert extract.main([str(shop_repo), "--exclude", "scripts/*"]) == 0
    stack_file = shop_repo / "docs" / "viz-code" / "stack.yaml"
    text = stack_file.read_text()
    assert text.startswith("# stack.yaml:") and "exclude:\n  - 'scripts/*'\n" in text
    assert extract.main([str(shop_repo)]) == 0
    s = json.loads((shop_repo / "docs" / "viz-code" / "structure.json").read_text())
    assert "scripts/run_once.py" in s["excluded"] and "scripts/run_once.py" not in s["files"]
    assert extract.main([str(shop_repo), "--exclude", "scripts/*", "--exclude", "pylib/*"]) == 0
    assert stack_file.read_text().count("exclude:") == 1
    assert "  - 'scripts/*'\n  - 'pylib/*'\n" in stack_file.read_text()


def test_exclude_list_is_rewritten_in_place_of_the_old_one(tmp_path):
    from vizcode import stack
    p = tmp_path / "stack.yaml"
    p.write_text("python:\n  ignore: [attrs]\nexclude:\n- gen/*\n# routes below\ngo:\n  ignore: [x]\n")
    assert stack.add_excludes(p, ["gen/*", "it's/*"]) == ["it's/*"]
    text = p.read_text()
    assert text == ("python:\n  ignore: [attrs]\n# routes below\ngo:\n  ignore: [x]\n"
                    "exclude:\n  - 'gen/*'\n  - 'it''s/*'\n")
    assert stack.load(p).excludes == ["gen/*", "it's/*"]
