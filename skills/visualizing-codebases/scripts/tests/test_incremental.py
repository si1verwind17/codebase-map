import json

import assemble as assemble_cli
import diff as diff_cli
import extract
from conftest import commit_all, git, with_stack, write_files
from meaning_fixture import CALL, MEANING, POST, WRITE

OUT = ("docs", "viz-code")


def scan(repo):
    """Full scan with the fixture meaning, then commit the map like a user would."""
    extract.main([str(repo)])
    (repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(repo)]) == 0
    return commit_all(repo, "add code map")


def rescan_plan(repo):
    extract.main([str(repo)])
    diff_cli.main([str(repo)])
    out = repo.joinpath(*OUT)
    stale = json.loads((out / "stale.json").read_text())
    meaning = json.loads((out / "meaning.json").read_text()) if (out / "meaning.json").exists() else None
    return stale, meaning


def test_map_commit_alone_changes_nothing(shop_repo, capsys):
    scan(shop_repo)
    stale, meaning = rescan_plan(shop_repo)
    assert stale["mode"] == "none"
    # files under docs/viz-code/ are ignored; only the scanner's .gitattributes line remains
    assert [c["path"] for c in stale["changed"]] == [".gitattributes"]


def test_edit_one_file_marks_only_its_facts_stale(shop_repo):
    scan(shop_repo)
    before = json.loads((shop_repo.joinpath(*OUT) / "code-map.json").read_text())
    write_files(shop_repo, {"worker/main.py": (shop_repo / "worker/main.py").read_text() + "\n# touched\n"})
    commit_all(shop_repo, "touch worker")
    stale, meaning = rescan_plan(shop_repo)
    assert stale["mode"] == "incremental"
    assert stale["stale_examples"] == []   # its signatures did not change
    assert [r["id"] for r in stale["stale_relations"]] == [POST]
    kept = {r["id"]: r for r in meaning["relations"]}
    assert set(kept) == {WRITE, CALL, POST}  # stale facts stay, so doing nothing never loses data
    assert kept[POST]["stale"] is True
    assert kept[WRITE] == next(r for r in before["relations"] if r["id"] == WRITE)  # untouched, no flag
    assert meaning["pins"] == MEANING["pins"] and meaning["unpinned"] == []
    assert "worker::worker.main#run/2" not in meaning["summaries"]  # its file changed


def test_assemble_refuses_unresolved_stale_facts(shop_repo, capsys):
    scan(shop_repo)
    write_files(shop_repo, {"worker/main.py": (shop_repo / "worker/main.py").read_text() + "\n# touched\n"})
    commit_all(shop_repo, "touch worker")
    rescan_plan(shop_repo)
    capsys.readouterr()
    assert assemble_cli.main([str(shop_repo)]) == 1
    err = capsys.readouterr().err
    assert f"relation {POST}: stale" in err


def test_removed_method_reports_orphans(shop_repo):
    scan(shop_repo)
    src = (shop_repo / "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala").read_text()
    write_files(shop_repo, {"shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala":
                            src.replace("def helper(x: Int): Int = x\n", "")})
    commit_all(shop_repo, "drop helper")
    stale, meaning = rescan_plan(shop_repo)
    # the file node held only top-level defs, so it disappears with helper
    assert stale["removed_nodes"] == ["shop::io.demo.shop.repo/OrderRepo.scala",
                                      "shop::io.demo.shop.repo/OrderRepo.scala#helper/1"]
    assert [r["id"] for r in stale["stale_relations"]] == [WRITE]  # its evidence file changed
    assert next(r for r in meaning["relations"] if r["id"] == WRITE)["stale"] is True
    orphan = [p for p in meaning["problems"] if p.get("source") == "diff"]
    assert orphan and "shop::io.demo.shop.repo/OrderRepo.scala#helper/1" in orphan[0]["removed"]


def test_full_rescan_triggers(shop_repo):
    scan(shop_repo)
    write_files(shop_repo, {"docker-compose.yml": "services:\n  shop: {build: .}\n"})
    commit_all(shop_repo, "drop worker service")
    stale, meaning = rescan_plan(shop_repo)
    assert stale["mode"] == "full" and "deployable" in stale["reason"]
    assert meaning is None  # no leftover meaning.json from the previous scan


def test_rewritten_history_forces_full(shop_repo):
    scan(shop_repo)
    git(shop_repo, "checkout", "-q", "--orphan", "rewritten")
    commit_all(shop_repo, "squashed history")
    cmap_path = shop_repo.joinpath(*OUT) / "code-map.json"
    cmap = json.loads(cmap_path.read_text())
    cmap["meta"]["commit"] = "1" * 40  # a commit the repo has never seen
    cmap_path.write_text(json.dumps(cmap))
    stale, meaning = rescan_plan(shop_repo)
    assert stale["mode"] == "full" and "no longer exists" in stale["reason"]
    assert meaning is None  # the old meaning.json is gone: a full rescan starts clean


def test_incremental_round_trip_is_valid(shop_repo):
    scan(shop_repo)
    write_files(shop_repo, {"worker/main.py": (shop_repo / "worker/main.py").read_text() + "\n# touched\n"})
    commit_all(shop_repo, "touch worker")
    before = json.loads((shop_repo.joinpath(*OUT) / "code-map.json").read_text())
    stale, meaning = rescan_plan(shop_repo)
    # the agent re-resolves each stale fact as still true: it clears the flag
    for fact in meaning["relations"]:
        fact.pop("stale", None)
    (shop_repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(meaning))
    assert assemble_cli.main([str(shop_repo)]) == 0
    cmap = json.loads((shop_repo.joinpath(*OUT) / "code-map.json").read_text())
    assert cmap["meta"]["commit"] == git(shop_repo, "rev-parse", "HEAD").strip()
    assert cmap["relations"] == before["relations"] and (cmap["pins"], cmap["examples"]) == (before["pins"], before["examples"])


def test_excluded_test_files_do_not_force_a_full_rescan(shop_repo):
    scan(shop_repo)
    write_files(shop_repo, {f"worker/test_more_{i}.py": "def test_x():\n    assert True\n" for i in range(6)})
    commit_all(shop_repo, "add tests")
    stale, meaning = rescan_plan(shop_repo)
    assert stale["mode"] == "incremental"


def test_a_removed_via_marks_its_relation_stale(shop_repo):
    import copy
    meaning = copy.deepcopy(MEANING)
    call = next(r for r in meaning["relations"] if r.get("via"))
    call["evidence"] = [e for e in call["evidence"] if e["file"] != "pylib/client.py"]
    extract.main([str(shop_repo)])
    (shop_repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(meaning))
    assert assemble_cli.main([str(shop_repo)]) == 0
    commit_all(shop_repo, "add code map")
    write_files(shop_repo, {"pylib/client.py": "from worker.util.helpers import fmt\n\n\ndef call_v2() -> str:\n    return fmt(1)\n"})
    commit_all(shop_repo, "rename call")
    stale, _ = rescan_plan(shop_repo)
    assert CALL in [r["id"] for r in stale["stale_relations"]]


def test_a_role_override_on_a_removed_package_is_dropped_not_refused(shop_repo, capsys):
    import copy
    meaning = copy.deepcopy(MEANING)
    meaning["roles"] = {"worker::worker.util/": {"role": "model", "why": "helpers only"}}
    extract.main([str(shop_repo)])
    (shop_repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(meaning))
    assert assemble_cli.main([str(shop_repo)]) == 0
    commit_all(shop_repo, "add code map")
    git(shop_repo, "rm", "-q", "-r", "worker/util")
    commit_all(shop_repo, "drop util")
    stale, meaning = rescan_plan(shop_repo)
    assert "worker::worker.util/" not in meaning.get("roles", {})



def test_topic_with_evidence_in_changed_file_goes_stale(shop_repo):
    m = json.loads(json.dumps(MEANING))
    m["nodes"].append({"id": "topic:kafka:orders", "kind": "topic", "name": "orders", "delivery": "fan-out",
                       "evidence": [{"file": "worker/main.py", "line": 1}]})
    m["relations"] += [
        {"kind": "event", "from": "svc:worker", "to": "topic:kafka:orders", "key": "orders",
         "confidence": "confirmed", "evidence": [{"file": "worker/main.py", "line": 2}]}]
    extract.main([str(shop_repo)])
    (shop_repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(m))
    assert assemble_cli.main([str(shop_repo)]) == 0
    commit_all(shop_repo, "add code map")
    write_files(shop_repo, {"worker/main.py": (shop_repo / "worker/main.py").read_text() + "\n# touched\n"})
    commit_all(shop_repo, "touch")
    stale, meaning = rescan_plan(shop_repo)
    assert stale["mode"] == "incremental"
    assert stale["stale_nodes"] == ["topic:kafka:orders"]
    kept = {n["id"]: n for n in meaning["nodes"]}
    assert kept["topic:kafka:orders"]["stale"] is True and kept["topic:kafka:orders"]["delivery"] == "fan-out"
    assert not kept["svc:shop"].get("stale")
    assert assemble_cli.main([str(shop_repo)]) != 0          # refused until re-resolved
    kept["topic:kafka:orders"].pop("stale")
    for r in meaning["relations"]:
        r.pop("stale", None)
    (shop_repo.joinpath(*OUT) / "meaning.json").write_text(json.dumps(meaning))
    assert assemble_cli.main([str(shop_repo)]) == 0


def _bump_scanner(repo, rename_via: tuple[str, str] | None = None):
    """Pretend the committed map came from an older scanner (optionally with a node the new scan lacks)."""
    path = repo.joinpath(*OUT) / "code-map.json"
    cmap = json.loads(path.read_text())
    cmap["meta"]["scanner_version"] = "0.0.0"
    if rename_via:
        old, new = rename_via
        for n in cmap["nodes"]:
            if n["id"] == old:
                n["id"] = new
        for r in cmap["relations"]:
            if r.get("via") == old:
                r["via"] = new
    path.write_text(json.dumps(cmap))
    commit_all(repo, "map from an older scanner")
    return cmap


def test_full_rescan_keeps_the_previous_meaning(shop_repo):
    scan(shop_repo)
    cmap = _bump_scanner(shop_repo)
    stale, meaning = rescan_plan(shop_repo)
    out = shop_repo.joinpath(*OUT)
    assert stale["mode"] == "full" and "version" in stale["reason"]
    assert stale["previous_meaning"] == "meaning.previous.json"
    assert meaning is None and not (out / "meaning.json").exists()
    prev = json.loads((out / "meaning.previous.json").read_text())
    assert set(prev) == {"domain_context", "nodes", "relations", "pins", "unpinned", "examples", "problems", "roles", "summaries"}
    runtime = [r for r in cmap["relations"] if r["kind"] not in ("uses-code", "calls")]
    assert prev["relations"] == runtime and (prev["pins"], prev["examples"]) == (cmap["pins"], cmap["examples"])
    assert not any(x.get("stale") for k in ("nodes", "relations") for x in prev[k])   # nothing suspect: nothing flagged
    assert prev["summaries"] == MEANING["summaries"]
    # the agent starts from it, checks every fact, and assembles: the seed is gone
    (out / "meaning.json").write_text(json.dumps(prev))
    assert assemble_cli.main([str(shop_repo)]) == 0
    assert not (out / "meaning.previous.json").exists()


def test_full_rescan_flags_facts_on_missing_ids_and_changed_files(shop_repo):
    scan(shop_repo)
    _bump_scanner(shop_repo, ("pylib::pylib.client#call/0", "pylib::pylib.client#call_old/0"))
    src = (shop_repo / "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala").read_text()
    write_files(shop_repo, {"shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala": src + "\n// touched\n"})
    commit_all(shop_repo, "touch the repo")
    stale, _ = rescan_plan(shop_repo)
    out = shop_repo.joinpath(*OUT)
    prev = json.loads((out / "meaning.previous.json").read_text())
    flagged = {r["id"] for r in prev["relations"] if r.get("stale")}
    assert flagged == {CALL, WRITE}           # via missing from the new structure; evidence file changed
    assert next(r for r in prev["relations"] if r["id"] == POST).get("stale") is None
    assert stale["mode"] == "full"
    # a later incremental run drops the seed
    scan_again = json.loads((out / "meaning.previous.json").read_text())
    for k in ("nodes", "relations"):
        for x in scan_again[k]:
            x.pop("stale", None)
    for r in scan_again["relations"]:
        if r.get("via") == "pylib::pylib.client#call_old/0":
            r["via"] = "pylib::pylib.client#call/0"
    (out / "meaning.json").write_text(json.dumps(scan_again))
    (out / "meaning.previous.json").write_text("{}")   # as if assemble never ran to exit 0
    assert assemble_cli.main([str(shop_repo)]) == 0
    commit_all(shop_repo, "map at the new scanner")
    write_files(shop_repo, {"worker/main.py": (shop_repo / "worker/main.py").read_text() + "\n# touched\n"})
    commit_all(shop_repo, "touch worker")
    (out / "meaning.previous.json").write_text("{}")
    stale, _ = rescan_plan(shop_repo)
    assert stale["mode"] == "incremental" and "previous_meaning" not in stale
    assert not (out / "meaning.previous.json").exists()


def test_a_different_scanned_folder_forces_full(shop_repo):
    scan(shop_repo)
    path = shop_repo.joinpath(*OUT) / "code-map.json"
    cmap = json.loads(path.read_text())
    cmap["meta"]["root"] = "elsewhere"
    path.write_text(json.dumps(cmap))
    commit_all(shop_repo, "map of another folder")
    stale, _ = rescan_plan(shop_repo)
    assert stale["mode"] == "full" and "scanned folder" in stale["reason"]
    prev = json.loads((shop_repo.joinpath(*OUT) / "meaning.previous.json").read_text())
    assert all(r.get("stale") for r in prev["relations"])    # what changed is unknown: every fact is suspect


def _none_summary(repo, capsys):
    out = repo.joinpath(*OUT)
    for name in ("index.html", "audit.md"):
        (out / name).unlink(missing_ok=True)
    extract.main([str(repo)])
    capsys.readouterr()
    assert diff_cli.main([str(repo)]) == 0
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1]), out


def test_none_refreshes_the_page_and_the_audit(shop_repo, capsys):
    scan(shop_repo)
    summary, out = _none_summary(shop_repo, capsys)
    assert summary["mode"] == "none"
    assert summary["refreshed"] is True
    assert summary["page"].startswith(str(out / "index.html"))
    assert summary["audit"].startswith(("Map audit:", "Map limits:"))
    assert (out / "index.html").is_file() and (out / "audit.md").is_file()
    assert "refresh_error" not in summary


def test_none_with_a_broken_viewer_reports_and_exits_0(shop_repo, tmp_path, monkeypatch, capsys):
    import view
    scan(shop_repo)
    broken = tmp_path / "viewer.html"
    broken.write_text("<html>no marker</html>")
    monkeypatch.setattr(view, "VIEWER", broken)
    summary, out = _none_summary(shop_repo, capsys)
    assert summary["mode"] == "none"
    assert "marker" in summary["refresh_error"]
    assert not (out / "index.html").exists()
    assert (out / "audit.md").is_file()   # the audit still runs


def test_incremental_does_not_refresh(shop_repo, capsys):
    scan(shop_repo)
    write_files(shop_repo, {"worker/main.py": (shop_repo / "worker/main.py").read_text() + "\n# touched\n"})
    commit_all(shop_repo, "touch worker")
    extract.main([str(shop_repo)])
    capsys.readouterr()
    assert diff_cli.main([str(shop_repo)]) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["mode"] == "incremental" and "refreshed" not in summary


STACK_A = ("# stack.yaml: written by the visualizing-codebases agent from this repo's code; read by extract.py.\n"
           "# Libraries and route styles the scanner does not know built in. Commit it; edit it by hand if a fact is wrong.\n"
           "python:\n  ignore: [alpha]\n")
STACK_CHANGED = "stack.yaml changed since the map was made"


def _map(repo):
    return json.loads(repo.joinpath(*OUT, "code-map.json").read_text())


def test_map_stamps_the_stack_digest(shop_repo):
    scan(shop_repo)
    assert "stack" not in _map(shop_repo)["meta"]
    with_stack(shop_repo, STACK_A)
    scan(shop_repo)
    digest = json.loads(shop_repo.joinpath(*OUT, "structure.json").read_text())["stack"]["digest"]
    assert digest and _map(shop_repo)["meta"]["stack"] == digest


def test_changed_stack_file_forces_full(shop_repo):
    with_stack(shop_repo, STACK_A)
    scan(shop_repo)
    with_stack(shop_repo, STACK_A.replace("alpha", "beta"))
    stale, _ = rescan_plan(shop_repo)
    assert stale["mode"] == "full" and stale["reason"] == STACK_CHANGED


def test_unchanged_stack_file_is_not_full(shop_repo):
    with_stack(shop_repo, STACK_A)
    scan(shop_repo)
    stale, _ = rescan_plan(shop_repo)
    assert stale["mode"] == "none"


def test_no_stack_file_on_both_sides_is_unchanged(shop_repo):
    scan(shop_repo)
    stale, _ = rescan_plan(shop_repo)
    assert stale["mode"] == "none"


def test_hand_added_stack_file_on_an_unstamped_map_forces_full(shop_repo):
    scan(shop_repo)
    with_stack(shop_repo, STACK_A)
    stale, _ = rescan_plan(shop_repo)
    assert stale["mode"] == "full" and stale["reason"] == STACK_CHANGED


def test_build_file_of_a_new_ecosystem_forces_full(shop_repo):
    scan(shop_repo)
    write_files(shop_repo, {"pom.xml": "<project/>\n"})
    commit_all(shop_repo, "add a maven build")
    stale, _ = rescan_plan(shop_repo)
    assert stale["mode"] == "full" and "deployable" in stale["reason"]


def test_new_languages_scanned_force_full(shop_repo):
    """Files in a newly supported language did not change, so only this rule sends the agent to them."""
    write_files(shop_repo, {"dashboard/app.ts": "export function main() {}\n", "dashboard/x.go": "package x\n"})
    commit_all(shop_repo, "dashboard")
    scan(shop_repo)
    cmap_path = shop_repo.joinpath(*OUT) / "code-map.json"
    cmap = json.loads(cmap_path.read_text())
    assert cmap["meta"]["languages"] == ["go", "python", "scala", "typescript"]
    cmap["meta"]["languages"] = ["python", "scala"]     # a map made before the scanner read them
    cmap_path.write_text(json.dumps(cmap))
    stale, meaning = rescan_plan(shop_repo)
    assert stale["mode"] == "full" and stale["reason"] == "new languages scanned: go, typescript"
    assert meaning is None


def test_python_scala_map_with_unchanged_languages_is_unchanged(shop_repo):
    scan(shop_repo)
    assert _map(shop_repo)["meta"]["languages"] == ["python", "scala"]
    stale, _ = rescan_plan(shop_repo)
    assert stale["mode"] == "none" and stale["reason"] is None
