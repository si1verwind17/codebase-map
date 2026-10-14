"""Smoke test on a big real Scala + Python repo. Set VIZCODE_REAL_REPO to run it.

The repo's own routes and tables stay local, like the repo: VIZCODE_REAL_REPO_EXPECT (default
~/.config/viz-code/real-repo-expect.json) holds `{"routes": {"<path prefix>": [[method, path], ...]},
"writes": [table, ...]}`, checked apart from the repo-independent checks; without it only those run. Parse
errors are allowed in up to 1% of the files, listed when over."""
import json
import os
from pathlib import Path

import pytest

from vizcode import mapcheck, structure
from vizcode.assemble import assemble

REPO = Path(os.environ.get("VIZCODE_REAL_REPO", "/nonexistent"))
EXPECT = Path(os.environ.get("VIZCODE_REAL_REPO_EXPECT", Path.home() / ".config/viz-code/real-repo-expect.json"))
pytestmark = pytest.mark.skipif(not (REPO / ".git").exists(), reason="VIZCODE_REAL_REPO not set")


@pytest.fixture(scope="module")
def built():
    return structure.build(REPO, "docs/viz-code")


def test_big_real_repo_structure(built):
    s = built
    errors = sorted(f for f, i in s["files"].items() if i["parse_error"])
    assert len(errors) <= len(s["files"]) / 100, f"{len(errors)} of {len(s['files'])} files: {errors}"
    assert s["stats"]["seconds"] < 10
    assert mapcheck.check(assemble(s, {})) == []


@pytest.mark.skipif(not EXPECT.is_file(), reason="no local route and table expectations")
def test_big_real_repo_expected_routes_and_tables(built):
    s = built
    expect = json.loads(EXPECT.read_text(encoding="utf-8"))
    for prefix, routes in expect["routes"].items():
        found = {(r["method"], r["path"]) for f, ff in s["facts"].items() if f.startswith(prefix) for r in ff["routes"]}
        assert {tuple(r) for r in routes} <= found, prefix
    writes = {t for ff in s["facts"].values() for q in ff["sql"] for t in q["writes"]}
    assert set(expect["writes"]) <= writes


def test_big_real_repo_assembles_with_calls_and_layout(built):
    cmap = assemble(built, {})
    assert mapcheck.check(cmap) == []
    assert sum(1 for r in cmap["relations"] if r["kind"] == "calls") > 500
    floors = cmap["layout"]["containers"]
    assert floors["site"]["strategy"] == "main-bus"
    assert max(len(f["items"]) for f in floors.values()) <= 24
