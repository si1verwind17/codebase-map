"""Small helpers several test folders share."""
import json

import assemble as assemble_cli
import extract
from conftest import commit_all
from meaning_fixture import MEANING

OUT = ("docs", "viz-code")


def write(tmp_path, text, raw=None):
    """A stack.yaml under tmp_path with `text` (or `raw` bytes)."""
    p = tmp_path / "stack.yaml"
    p.write_bytes(raw if raw is not None else text.encode())
    return p


def routes(s, f):
    return [(r["method"], r["path"], r["handler"], r["line"], r["framework"], r["source"])
            for r in s["facts"][f].get("routes", [])]


def sinks(s, f):
    return sorted((x["kind"], x["lib"]) for x in s["facts"][f]["sinks"])


def tables(s, f):
    return [(t["table"], t["line"], t["in"], t["kind"], t["pattern"]) for t in s["facts"][f].get("tables", [])]


def scan(repo):
    """Full scan with the fixture meaning, then commit the map like a user would."""
    extract.main([str(repo)])
    (repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(repo)]) == 0
    return commit_all(repo, "add code map")
