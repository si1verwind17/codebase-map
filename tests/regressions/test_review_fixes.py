"""Regression tests (symlinks, subdirectories, excludes,
route idioms, commit drift, defaulted libraries, output-dir paths)."""
import copy
import json
import os

import assemble as assemble_cli
import diff as diff_cli
import extract
from conftest import SHOP, commit_all, write_files
from meaning_fixture import MEANING

from vizcode import ids, structure
from vizcode.adapters import python as py
from vizcode.adapters import scala


def test_symlink_outside_repo_is_skipped_not_fatal(make_repo):
    repo = make_repo({"app/__init__.py": "", "app/main.py": "def f():\n    pass\n"})
    os.symlink("/etc/hostname", repo / "app" / "link.txt")
    commit_all(repo, "add link")
    s = structure.build(repo, "docs/viz-code")
    assert "app/main.py" in s["files"]
    assert {"file": "app/link.txt", "reason": "link points outside the repository; not extracted"} in s["skipped"]


def test_non_git_folder_is_rejected(tmp_path, capsys):
    assert extract.main([str(tmp_path)]) == 2
    assert "error" in capsys.readouterr().err


def test_default_excludes_keep_production_files(make_repo):
    repo = make_repo({
        "script/backtest_config.py": "def load():\n    pass\n",
        "latest_price.py": "def price():\n    pass\n",
        "project/__init__.py": "", "project/core.py": "def run():\n    pass\n",
        "build/__init__.py": "", "build/steps.py": "def step():\n    pass\n",
        "pkg/__init__.py": "", "pkg/test_util.py": "def test_u():\n    pass\n",
    })
    s = structure.build(repo, "docs/viz-code")
    for f in ("script/backtest_config.py", "latest_price.py", "project/core.py", "build/steps.py"):
        assert f in s["files"], f
    assert "pkg/test_util.py" not in s["files"]
    assert "pkg/test_util.py" in s["excluded"]
    assert "Excluded files (1)" in structure.summary_md(s)


def test_sbt_project_dir_still_excluded(shop_repo):
    write_files(shop_repo, {"project/Deps.scala": "object Deps\n"})
    commit_all(shop_repo)
    s = structure.build(shop_repo, "docs/viz-code")
    assert "project/Deps.scala" not in s["files"]


def test_tapir_val_endpoints_and_path_capture_nodes():
    base = ('package io.demo.api\n\nobject BaseEndpoint {\n  private val base = endpoint\n'
            '  object V1 {\n    private val v1 = base.in("v1")\n    object Invoices {\n'
            '      private val invoices = v1.in("invoices")\n'
            '      val invoiceById = invoices.in(path[Long]("id"))\n    }\n  }\n}\n')
    api = ('package io.demo.api\n\nobject GetInvoiceApi {\n'
           '  val endpoint = BaseEndpoint.V1.Invoices.invoiceById.get.out(jsonBody[Out])\n}\n')
    mod = {"id": "mod:svc", "path": "svc", "lang": "scala", "build": "sbt"}
    reg = ids.IdRegistry()
    rb = scala.parse(base.encode(), "svc/src/main/scala/io/demo/api/BaseEndpoint.scala", mod, reg)
    ra = scala.parse(api.encode(), "svc/src/main/scala/io/demo/api/GetInvoiceApi.scala", mod, reg)
    from vizcode import routes
    resolved = routes.resolve_tapir({**rb["tapir"]["vals"], **ra["tapir"]["vals"]})
    assert resolved["BaseEndpoint.V1.Invoices.invoiceById"] == ["v1", "invoices", "{id}"]
    found = [(m, p, h) for h, _, body in ra["tapir"]["bodies"] for m, p in routes.tapir_uses(body, resolved)]
    assert found == [("GET", "/v1/invoices/{id}", "svc::io.demo.api.GetInvoiceApi$")]


def test_fastapi_annotated_router_and_include_router():
    src = (b'from fastapi import APIRouter, FastAPI\n\napi: APIRouter = APIRouter(prefix="/v1")\n'
           b'app = FastAPI()\n\n\n@api.post("/orders")\ndef create(o: dict) -> dict:\n    return o\n\n\n'
           b'app.include_router(api, prefix="/shop")\n')
    mod = {"id": "mod:w", "path": "w", "lang": "python", "build": "python-package"}
    res = py.parse(src, "w/main.py", mod, ids.IdRegistry())
    assert [(r["method"], r["path"]) for r in res["routes"]] == [("POST", "/v1/orders")]
    assert res["includes"] == [{"app": "app", "router": "api", "prefix": "/shop", "line": 12}]


def test_assemble_refuses_when_head_moved(shop_repo, capsys):
    extract.main([str(shop_repo)])
    (shop_repo / "docs/viz-code/meaning.json").write_text(json.dumps(MEANING))
    write_files(shop_repo, {"worker/main.py": SHOP["worker/main.py"] + "\n# later\n"})
    commit_all(shop_repo, "someone else commits")
    capsys.readouterr()
    assert assemble_cli.main([str(shop_repo)]) == 1
    assert "HEAD moved" in capsys.readouterr().err


def test_defaulted_library_keeps_being_reported(shop_repo):
    meaning = copy.deepcopy(MEANING)
    meaning["nodes"][2]["modules"] = ["common", "pylib"]  # scripts left unclaimed
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(meaning))
    assert assemble_cli.main([str(shop_repo)]) == 0
    commit_all(shop_repo, "map")
    write_files(shop_repo, {"pylib/client.py": SHOP["pylib/client.py"] + "\n# touched\n"})
    commit_all(shop_repo, "touch")
    extract.main([str(shop_repo)])
    diff_cli.main([str(shop_repo)])
    kept = json.loads((out / "meaning.json").read_text())
    for fact in kept["relations"]:
        fact.pop("stale", None)
    (out / "meaning.json").write_text(json.dumps(kept))
    assert assemble_cli.main([str(shop_repo)]) == 0
    cmap = json.loads((out / "code-map.json").read_text())
    assert any("scripts" in p["text"] and p.get("source") == "assemble" for p in cmap["problems"])
    assert next(n for n in cmap["nodes"] if n["id"] == "lib:scripts")["defaulted"] is True


def test_absolute_out_dir_inside_repo_is_normalised(shop_repo):
    assert extract.main([str(shop_repo), "--out-dir", str(shop_repo / "out" / "map")]) == 0
    (shop_repo / "out/map/meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo), "--out-dir", str(shop_repo / "out" / "map") + "/"]) == 0
    assert "code-map.json linguist-generated=true -diff" in (shop_repo / "out/map/.gitattributes").read_text().splitlines()


def test_out_dir_outside_repo_is_rejected(shop_repo, tmp_path, capsys):
    assert extract.main([str(shop_repo), "--out-dir", str(tmp_path / "elsewhere")]) == 2
    assert "inside the repository" in capsys.readouterr().err
