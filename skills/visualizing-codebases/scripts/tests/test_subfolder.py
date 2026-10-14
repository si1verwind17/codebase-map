"""A project that lives in a subfolder of a larger git repository."""
import json

import assemble as assemble_cli
import diff as diff_cli
import extract
import pytest
from conftest import SHOP, commit_all, git, write_files
from meaning_fixture import MEANING

from vizcode import gitsrc, mapcheck

PREFIX = "projects/shop"
OUT = ("docs", "viz-code")


@pytest.fixture
def mono(make_repo):
    files = {f"{PREFIX}/{k}": v for k, v in SHOP.items()}
    files["other/tool.py"] = "def tool():\n    return 1\n"
    files["README.md"] = "outer\n"
    repo = make_repo(files, name="mono")
    return repo, repo / PREFIX


def scan(proj):
    assert extract.main([str(proj)]) == 0
    (proj.joinpath(*OUT) / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(proj)]) == 0
    return commit_all(proj, "add code map")


def plan(proj):
    assert extract.main([str(proj)]) == 0
    assert diff_cli.main([str(proj)]) == 0
    return json.loads((proj.joinpath(*OUT) / "stale.json").read_text())


def test_extract_subfolder_paths_are_project_relative(mono):
    repo, proj = mono
    assert extract.main([str(proj)]) == 0
    s = json.loads((proj.joinpath(*OUT) / "structure.json").read_text())
    assert "worker/main.py" in s["files"]
    assert not any(f.startswith(("projects/", "other/")) for f in s["files"])
    assert s["meta"]["commit"] == gitsrc.head_commit(repo)
    assert s["meta"]["repo"] == "shop"
    assert s["meta"]["root"] == PREFIX


def test_top_level_root_is_null(shop_repo):
    assert extract.main([str(shop_repo)]) == 0
    s = json.loads(shop_repo.joinpath(*OUT, "structure.json").read_text())
    assert s["meta"]["root"] is None
    assert s["meta"]["repo"] == shop_repo.name


def test_subfolder_map_validates(mono):
    _, proj = mono
    scan(proj)
    cmap = json.loads((proj.joinpath(*OUT) / "code-map.json").read_text())
    assert cmap["meta"]["root"] == PREFIX
    assert mapcheck.check(cmap) == []


def test_change_inside_subfolder_flags_facts(mono):
    _, proj = mono
    scan(proj)
    write_files(proj, {"worker/main.py": (proj / "worker/main.py").read_text() + "\n# touched\n"})
    commit_all(proj, "edit")
    stale = plan(proj)
    assert stale["mode"] == "incremental"
    assert "worker/main.py" in [c["path"] for c in stale["changed"]]
    assert stale["stale_relations"] or stale["stale_nodes"]


def test_change_outside_subfolder_flags_nothing(mono):
    repo, proj = mono
    scan(proj)
    write_files(repo, {"other/tool.py": "def tool():\n    return 2\n", "README.md": "changed\n"})
    commit_all(repo, "outside")
    stale = plan(proj)
    assert stale["mode"] == "none"
    assert [c["path"] for c in stale["changed"]] == [".gitattributes"]   # the map commit itself, inside the folder
    assert not (stale["stale_relations"] or stale["stale_nodes"])


def test_uncommitted_subfolder_is_a_clear_error(mono, capsys):
    repo, proj = mono
    new = repo / "fresh"
    new.mkdir()
    (new / "a.py").write_text("x = 1\n")
    assert extract.main([str(new)]) == 2
    assert "error" in capsys.readouterr().err


def test_summary_header_names_the_folder(mono):
    _, proj = mono
    assert extract.main([str(proj)]) == 0
    md = (proj.joinpath(*OUT) / "summary.md").read_text()
    head = md.splitlines()[2]
    assert head.endswith(f" — folder `{PREFIX}` of the repository")
    assert ":./<path>`" in md


def test_show_with_dot_slash_reads_the_subfolder_file(mono):
    repo, proj = mono
    head = gitsrc.head_commit(repo)
    assert git(proj, "show", f"{head}:./worker/main.py") == (proj / "worker/main.py").read_text()
    with pytest.raises(Exception):   # without ./ the path resolves from the git top level
        git(proj, "show", f"{head}:worker/main.py")
