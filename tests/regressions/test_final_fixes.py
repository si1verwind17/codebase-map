"""Final-review fixes: internal-name index, explicit encodings, digest and header line endings, route method source,
Scala relative imports, and the committed identity of the demo's structure.json."""
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import GIT_ENV, commit_all, git, with_stack

from vizcode import stack, structure

SKILL = Path(__file__).resolve().parents[2]   # the repo root: demo/ sits here
SCRIPTS = SKILL / "skills" / "visualizing-codebases" / "scripts"
EXTRACT = SCRIPTS / "extract.py"


def old_is_internal(target, internal):
    return any(target == n or target.startswith(n + ".") or n.startswith(target + ".") for n in internal)


@pytest.mark.parametrize("target", ["a", "a.b", "a.b.c", "a.b.c.d", "a.bc", "ab", "x", "x.y", "q.r.s", "q", "q.r", "", "m.n.o.p"])
def test_is_internal_same_as_the_scan_over_every_name(target):
    internal = {"a.b", "x", "q.r.s", "m.n.o"}
    assert stack._is_internal(target, stack._index(internal)) == old_is_internal(target, internal)


# --- encodings ---------------------------------------------------------------------------------------------

def test_scripts_name_an_encoding_on_text_reads_and_writes():
    bad = []
    for path in sorted(SCRIPTS.rglob("*.py")):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"\.(?:read_text|write_text)\(|(?<![\w.])open\(", text):
            depth, k = 1, m.end()
            while depth:
                depth += {"(": 1, ")": -1}.get(text[k], 0)
                k += 1
            if "encoding=" not in text[m.end():k] and "mode=" not in text[m.end():k]:
                bad.append(f"{path.relative_to(SCRIPTS)}:{text.count(chr(10), 0, m.start()) + 1}")
    assert bad == []


# --- digest and header --------------------------------------------------------------------------------------

def test_digest_same_for_lf_crlf_and_bom(tmp_path):
    text = "python:\n  ignore: [a]\n"
    digests = set()
    for i, raw in enumerate([text.encode(), text.replace("\n", "\r\n").encode(), b"\xef\xbb\xbf" + text.encode()]):
        p = tmp_path / f"s{i}.yaml"
        p.write_bytes(raw)
        digests.add(stack.load(p).digest)
    assert len(digests) == 1 and None not in digests


def test_header_takes_the_files_line_ending(tmp_path):
    p = tmp_path / "stack.yaml"
    p.write_bytes(b"python:\r\n  ignore: [a]\r\n")
    stack.ensure_header(p)
    raw = p.read_bytes()
    assert raw == stack.HEADER.replace("\n", "\r\n").encode() + b"python:\r\n  ignore: [a]\r\n"
    stack.ensure_header(p)
    assert p.read_bytes() == raw
    q = tmp_path / "lf.yaml"
    q.write_bytes(b"python: {}\n")
    stack.ensure_header(q)
    assert q.read_bytes() == stack.HEADER.encode() + b"python: {}\n"


def test_extract_read_only_stack_yaml_is_an_error_not_a_traceback(quart_repo):
    path = with_stack(quart_repo, "python:\n  ignore: [marshmallow]\n")
    path.chmod(0o444)
    try:
        if os.access(path, os.W_OK):
            pytest.skip("file permissions are not enforced here")
        p = subprocess.run([sys.executable, str(EXTRACT), str(quart_repo)], capture_output=True, text=True)
    finally:
        path.chmod(0o644)
    assert p.returncode == 2
    assert p.stderr.startswith("error: ") and "Traceback" not in p.stderr


# --- route method source ------------------------------------------------------------------------------------

def test_methods_group_alone_needs_a_method_fallback(tmp_path):
    p = tmp_path / "stack.yaml"
    regex = r"@r\(\"(?P<path>[^\"]*)\"\)(?:\s*methods=\[(?P<methods>[^\]]*)\])?"
    p.write_text("python:\n  routes:\n    - {name: r, path: literal, regex: '" + regex + "'}\n", encoding="utf-8")
    with pytest.raises(stack.StackError) as e:
        stack.load(p)
    assert "stack.yaml: python.routes[0] (r): no method source" in str(e.value)
    p.write_text("python:\n  routes:\n    - {name: r, path: literal, method: GET, regex: '" + regex + "'}\n", encoding="utf-8")
    st = stack.load(p)
    got = stack.find_routes(st, "python", '@r("/a")\n@r("/b") methods=["post"]\n', [], [], "f")
    assert [(r["method"], r["path"]) for r in got] == [("GET", "/a"), ("POST", "/b")]


# --- Scala relative package imports ------------------------------------------------------------------------

def test_scala_relative_package_import_is_local(make_repo):
    repo = make_repo({
        "build.sbt": 'lazy val s = (project in file("s"))\n',
        "s/src/main/scala/com/acme/A.scala": "package com.acme\nimport model.user\nimport model.*\nimport other.thing\n"
                                             "import org.far.x\n\nobject A\n",
        "s/src/main/scala/com/acme/model/B.scala": "package com.acme.model\nimport util.helper\n\nobject B\n",
        "s/src/main/scala/com/acme/util/C.scala": "package com.acme.util\n\nobject C\n",
    })
    got = {u["prefix"] for u in structure.build(repo, "docs/viz-code")["stack"]["unrecognised"]}
    assert got == {"other.thing", "org.far"}


# --- committed identity of the demo's structure.json --------------------------------------------------------

# re-pinned for SCANNER_VERSION 0.10.0: the version string, `visibility` on the fields of the Scala case classes, and
# the `unscanned` report; then for the demo's features/ and forecast/ moving from Flyte to Airflow DAGs; then for
# interpolated table names (`{table('x')}`) no longer read as tables; then for SCANNER_VERSION 0.11.0: the version
# string and `ctor` on classes; then for SCANNER_VERSION 0.12.0: the version string
DEMO_STRUCTURE_SHA256 = "1549bec881accb6fa1a0bbb0dbef25a19ca604f014660ef45800dd28bf976846"
# the hash with the trace keys (`fields` and `ctor` on classes, `refs` and `returns_refs` in signatures) taken
# out: the value from before those keys existed, with the `queues` fact of 0.6.0, and the version strings, callees,
# lines and `optional` of 0.7.0, the version string, `generated` list and proto `messages` of 0.8.0, the version
# strings of 0.9.0 and 0.10.0, the `unscanned` report, the demo's features/ and forecast/ as Airflow DAGs, no
# interpolated table names, and the version strings of 0.11.0 and 0.12.0. If it moves, the scanner changed something besides the
# trace keys
DEMO_STRUCTURE_SHA256_WITHOUT_TRACE_KEYS = "0c788252a58e50dc6fba87322bf5c3bc14b8328aad903faa09a6e4651d3cccb0"


def _without_trace_keys(s: dict) -> dict:
    s = copy.deepcopy(s)
    for n in s["nodes"]:
        n.pop("fields", None)
        n.pop("ctor", None)
        if sig := n.get("signature"):
            sig.pop("returns_refs", None)
            for p in sig["params"]:
                p.pop("refs", None)
    return s


def _digest(s: dict) -> str:
    return hashlib.sha256(json.dumps(s, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_demo_structure_identity(tmp_path):
    """structure.json of the demo, minus the stack block, the commit and the run time, hashes to a pinned value
    (spec section 8: the scanner generalisation changes nothing else). If this fails after a deliberate
    scanner or demo change, check the difference is what you meant, then take the new hash from the assert message
    and replace DEMO_STRUCTURE_SHA256. The trace keys are checked apart: without them the hash must not move."""
    repo = tmp_path / "parking-city"
    for rel in git(SKILL, "ls-files", "demo/parking-city").split():
        dest = repo / Path(rel).relative_to("demo/parking-city")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SKILL / rel, dest)
    git(repo, "init", "-q", "-b", "main")
    commit_all(repo)
    s = structure.build(repo, "docs/viz-code")
    s.pop("stack")
    s["meta"].pop("commit")
    s["stats"].pop("seconds")
    assert _digest(_without_trace_keys(s)) == DEMO_STRUCTURE_SHA256_WITHOUT_TRACE_KEYS, \
        "demo structure.json changed beyond fields/ctor/refs/returns_refs"
    got = _digest(s)
    assert got == DEMO_STRUCTURE_SHA256, f"demo structure.json changed: new hash {got}"
