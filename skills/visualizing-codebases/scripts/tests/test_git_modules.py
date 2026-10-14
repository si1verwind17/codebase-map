from pathlib import Path

import pytest
from conftest import commit_all, git, write_files

from vizcode import gitsrc
from vizcode.modules import detect_modules


def test_export_tree_has_committed_content_only(shop_repo, tmp_path):
    head = gitsrc.head_commit(shop_repo)
    (shop_repo / "worker" / "main.py").write_text("UNCOMMITTED")
    (shop_repo / "worker" / "new.py").write_text("x = 1\n")
    dest = tmp_path / "export"
    dest.mkdir()
    gitsrc.export_tree(shop_repo, head, dest)
    assert "UNCOMMITTED" not in (dest / "worker" / "main.py").read_text()
    assert not (dest / "worker" / "new.py").exists()


def test_changed_files_reports_rename(shop_repo):
    old = gitsrc.head_commit(shop_repo)
    git(shop_repo, "mv", "pylib/client.py", "pylib/api_client.py")
    write_files(shop_repo, {"worker/util/helpers.py": "def fmt(code):\n    return 'x'\n"})
    new = commit_all(shop_repo)
    changed = {c["path"]: c for c in gitsrc.changed_files(shop_repo, old, new)}
    assert changed["pylib/api_client.py"] == {"status": "R", "old_path": "pylib/client.py",
                                              "path": "pylib/api_client.py"}
    assert changed["worker/util/helpers.py"]["status"] == "M"


def test_commit_exists_and_not_a_repo(shop_repo, tmp_path):
    assert gitsrc.commit_exists(shop_repo, gitsrc.head_commit(shop_repo))
    assert not gitsrc.commit_exists(shop_repo, "0" * 40)
    with pytest.raises(gitsrc.GitError):
        gitsrc.head_commit(tmp_path)


def test_detect_modules(shop_repo):
    files = ["common/src/main/scala/io/demo/common/db/Db.scala",
             "shop/src/main/scala/io/demo/shop/api/OrderApi.scala",
             "worker/main.py", "worker/util/helpers.py", "pylib/client.py",
             "scripts/run_once.py", "project/Deps.scala"]
    modules, file_mod, unassigned = detect_modules(Path(shop_repo), files)
    by_id = {m["id"]: m for m in modules}
    assert by_id["mod:shop"] == {"id": "mod:shop", "path": "shop", "lang": "scala", "build": "sbt"}
    assert by_id["mod:worker"]["build"] == "python-package"
    assert by_id["mod:scripts"]["build"] == "python-scripts"
    assert file_mod["worker/util/helpers.py"] == "mod:worker"
    assert file_mod["pylib/client.py"] == "mod:pylib"
    assert unassigned == ["project/Deps.scala"]


def test_detect_modules_empty_sbt_root(make_repo):
    """Empty sbt projects with no source files are not included as modules."""
    repo = make_repo({
        "build.sbt": 'lazy val util = (project in file("util"))\nlazy val api = (project in file("api"))\nlazy val empty = (project in file("empty"))\n',
        "util/src/main/scala/Demo.scala": "object Demo",
        "api/src/main/scala/Api.scala": "object Api",
        "empty/build.sbt": "// empty subproject",
    })
    files = [
        "util/src/main/scala/Demo.scala",
        "api/src/main/scala/Api.scala",
    ]
    modules, file_mod, unassigned = detect_modules(Path(repo), files)
    by_id = {m["id"]: m for m in modules}

    # Real modules should be found
    assert "mod:util" in by_id
    assert "mod:api" in by_id
    # Empty module (no source files) should NOT be a module
    assert "mod:empty" not in by_id
    # All files should be assigned
    assert len(unassigned) == 0
