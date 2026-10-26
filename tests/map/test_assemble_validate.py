import copy
import json
import subprocess

import assemble as assemble_cli
import extract
import validate as validate_cli
from meaning_fixture import MEANING, POST

from vizcode.map import mapcheck
from vizcode.scan import structure
from vizcode.map.assemble import assemble, meaning_errors


def built(shop_repo, meaning=MEANING):
    return assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(meaning))


def test_assembled_map_is_valid(shop_repo):
    cmap = built(shop_repo)
    assert mapcheck.check(cmap) == []
    nodes = {n["id"]: n for n in cmap["nodes"]}
    assert nodes["shop::io.demo.shop.api/"]["parent"] == "svc:shop"
    assert nodes["pylib::pylib/"]["parent"] == "lib:common"
    assert nodes["worker::worker.main#run/2"]["summary"].startswith("Runs a job")
    rels = {r["id"]: r for r in cmap["relations"]}
    assert POST in rels
    assert "r:uses-code:lib:common->svc:worker:" in rels           # pylib -> worker, rolled up
    assert "r:uses-code:svc:shop->lib:common:" in rels
    assert len(cmap["meta"]["commit"]) == 40 and cmap["meta"]["languages"] == ["python", "scala"]


def test_unclaimed_module_defaults_to_library(shop_repo):
    meaning = copy.deepcopy(MEANING)
    meaning["nodes"][2]["modules"] = ["common", "pylib"]          # scripts left unclaimed
    cmap = built(shop_repo, meaning)
    assert mapcheck.check(cmap) == []
    assert any(n["id"] == "lib:scripts" for n in cmap["nodes"])
    assert any(p["source"] == "assemble" and "scripts" in p["text"] for p in cmap["problems"])


def test_empty_meaning_still_valid(shop_repo):
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), {})
    assert mapcheck.check(cmap) == []


def test_rule_violations_are_reported(shop_repo):
    cmap = built(shop_repo)
    cmap["relations"].append({"id": "r:x", "kind": "event", "from": "svc:shop", "to": "svc:worker",
                              "confidence": "inferred", "evidence": [{"file": "a"}]})
    cmap["nodes"].append({"id": "db:x/t", "kind": "table", "parent": "svc:shop", "name": "t"})
    cmap["relations"][0]["via"] = "pylib::pylib.client#gone/0"
    cmap["relations"].append({"id": "r:lib", "kind": "db-write", "from": "pylib::pylib.client#call/0",
                              "to": "db:postgres:DB_HOST/public.orders", "confidence": "confirmed",
                              "evidence": [{"file": "pylib/client.py", "line": 4}]})
    errors = "\n".join(mapcheck.check(cmap))
    for expected in ("r:x: inferred without why", "r:x: event must start or end at a topic node",
                     "table cannot sit under service",
                     "via pylib::pylib.client#gone/0 missing",
                     "r:lib: runtime relation starts inside library lib:common"):
        assert expected in errors


def test_schema_rejects_missing_evidence_and_a_bad_pin(shop_repo):
    cmap = built(shop_repo)
    cmap["relations"][0]["evidence"] = []
    cmap["pins"][0]["direction"] = "sideways"
    errors = "\n".join(mapcheck.check(cmap))
    assert "schema:" in errors


def test_assemble_and_validate_cli(shop_repo, capsys):
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    assert validate_cli.main([str(out / "code-map.json")]) == 0
    assert "code-map.json linguist-generated=true -diff" in (out / ".gitattributes").read_text().splitlines()
    assert not (shop_repo / ".gitattributes").exists()              # nothing outside the output folder
    assert "structure.json" in (out / ".gitignore").read_text()
    (out / ".gitattributes").write_text("*.svg binary\n")           # the user's own lines stay
    assert assemble_cli.main([str(shop_repo)]) == 0
    assert assemble_cli.main([str(shop_repo)]) == 0                 # idempotent: no duplicate line
    assert (out / ".gitattributes").read_text().splitlines() == ["*.svg binary", "code-map.json linguist-generated=true -diff"]


def test_git_applies_the_output_folders_gitattributes(shop_repo):
    extract.main([str(shop_repo)])
    (shop_repo / "docs/viz-code/meaning.json").write_text(json.dumps(MEANING))
    assert assemble_cli.main([str(shop_repo)]) == 0
    attrs = subprocess.run(["git", "check-attr", "-a", "docs/viz-code/code-map.json"], cwd=shop_repo,
                           capture_output=True, text=True, check=True).stdout
    assert "linguist-generated: true" in attrs and "diff: unset" in attrs


def test_audit_md_is_gitignored():
    from vizcode.map.assemble import GITIGNORE
    assert "audit.md" in GITIGNORE


def test_assemble_exit_0_prints_the_audit_summary(shop_repo, capsys):
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    (out / "meaning.json").write_text(json.dumps(MEANING))
    capsys.readouterr()
    assert assemble_cli.main([str(shop_repo)]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith(("Map limits: ", "Map audit: "))
    assert "Drawing checks: skipped — VIZ_AUDIT=0" in (out / "audit.md").read_text()   # conftest sets it
    assert "audit.md" in (out / ".gitignore").read_text()


def test_assemble_cli_invalid_meaning(shop_repo, capsys):
    extract.main([str(shop_repo)])
    out = shop_repo / "docs" / "viz-code"
    bad = copy.deepcopy(MEANING)
    bad["relations"][1]["to"] = "db:missing"
    (out / "meaning.json").write_text(json.dumps(bad))
    assert assemble_cli.main([str(shop_repo)]) == 1
    assert (out / "code-map.invalid.json").exists() and not (out / "code-map.json").exists()
    assert "db:missing missing" in capsys.readouterr().err


def test_an_edited_relation_takes_the_id_of_its_new_content(shop_repo):
    meaning = copy.deepcopy(MEANING)
    rel = meaning["relations"][2]
    rel["id"] = "r:db-write:old->thing:table old"   # kept from a previous map, then edited
    cmap = built(shop_repo, meaning)
    ids = [r["id"] for r in cmap["relations"]]
    assert "r:db-write:old->thing:table old" not in ids
    assert f"r:db-write:{rel['from']}->{rel['to']}:{rel['key']}" in ids


def _run_with(shop_repo, meaning, capsys):
    extract.main([str(shop_repo)])
    (shop_repo / "docs" / "viz-code" / "meaning.json").write_text(json.dumps(meaning))
    code = assemble_cli.main([str(shop_repo)])
    return code, capsys.readouterr().err


def test_malformed_meaning_gives_a_fix_list_not_a_traceback(shop_repo, capsys):
    meaning = copy.deepcopy(MEANING)
    del meaning["relations"][0]["kind"]
    del meaning["nodes"][0]["id"]
    code, err = _run_with(shop_repo, meaning, capsys)
    assert code == 1
    assert "relation 1" in err and "kind" in err and "node 1" in err and "id" in err


def test_calls_in_meaning_are_rejected(shop_repo, capsys):
    meaning = copy.deepcopy(MEANING)
    meaning["relations"].append({"kind": "calls", "from": "svc:worker", "to": "svc:shop", "confidence": "inferred",
                                 "why": "x", "evidence": []})
    code, err = _run_with(shop_repo, meaning, capsys)
    assert code == 1 and "calls are resolved by the scanner" in err


def test_role_overrides_need_a_known_package_a_valid_role_and_a_why(shop_repo, capsys):
    meaning = copy.deepcopy(MEANING)
    meaning["roles"] = {"shop::io.demo.shop.repo/": {"role": "storage"},
                        "shop::io.demo.shop.api/": {"role": "gateway", "why": "x"},
                        "shop::io.demo.nope/": {"role": "logic", "why": "x"}}
    code, err = _run_with(shop_repo, meaning, capsys)
    assert code == 1
    assert "shop::io.demo.shop.repo/" in err and "why" in err
    assert "gateway" in err and "shop::io.demo.nope/" in err


def test_user_lines_in_the_out_dir_gitignore_survive(shop_repo, capsys):
    out = shop_repo / "docs" / "viz-code"
    out.mkdir(parents=True, exist_ok=True)
    (out / ".gitignore").write_text("my-notes.md\n")
    code, _ = _run_with(shop_repo, MEANING, capsys)
    assert code == 0
    lines = (out / ".gitignore").read_text().split()
    assert "my-notes.md" in lines and "structure.json" in lines and lines.count("index.html") == 1


def test_a_sticky_rescan_writes_the_same_bytes(shop_repo, capsys):
    code, _ = _run_with(shop_repo, MEANING, capsys)
    first = json.loads((shop_repo / "docs" / "viz-code" / "code-map.json").read_text())
    text1 = (shop_repo / "docs" / "viz-code" / "code-map.json").read_text()
    assert assemble_cli.main([str(shop_repo)]) == 0
    text2 = (shop_repo / "docs" / "viz-code" / "code-map.json").read_text()
    strip = lambda t: t.replace(json.loads(t)["meta"]["scanned_at"], "")
    assert strip(text1) == strip(text2), "key order changed between a fresh and a sticky run"
    assert first["layout"]


def test_a_repo_without_sources_says_so(make_repo):
    repo = make_repo({"README.md": "# nothing to scan\n"})
    cmap = assemble(structure.build(repo, "docs/viz-code"), {})
    assert any("no source files in a supported language (python, scala, java, kotlin" in p["text"]
               for p in cmap["problems"])


def test_wrong_top_level_types_give_a_fix_list(shop_repo, capsys):
    for bad in ({"nodes": None}, {"roles": ["x"]}, {"problems": ["text"]}, {"relations": {}}):
        code, err = _run_with(shop_repo, {**copy.deepcopy(MEANING), **bad}, capsys)
        assert code == 1 and "must be" in err, bad


def test_two_relations_with_the_same_content_are_reported(shop_repo, capsys):
    meaning = copy.deepcopy(MEANING)
    twin = copy.deepcopy(meaning["relations"][1])
    twin["via"] = "pylib::pylib.client#other/0"
    meaning["relations"].append(twin)
    code, err = _run_with(shop_repo, meaning, capsys)
    assert code == 1 and "relation 4 duplicates relation 2" in err


def test_one_method_enqueuing_two_jobs_on_one_queue_keys_each_job():
    """A job queue is a topic; each enqueue is an `event` keyed by its job, so two jobs one method enqueues on the
    same queue are two relations, and each job's run method is a consumer of its own key."""
    enqueue, queue = "web::shop.orders#place/1", "topic:redis:default"
    rel = lambda frm, to, key: {"kind": "event", "from": frm, "to": to, "key": key, "confidence": "confirmed",
                                "evidence": [{"file": "shop/orders.py", "line": 3}]}
    meaning = {"relations": [rel(enqueue, queue, "job SendReceipt"), rel(enqueue, queue, "job ReserveStock"),
                             rel(queue, "worker::jobs.SendReceipt#perform/1", "job SendReceipt"),
                             rel(queue, "worker::jobs.ReserveStock#perform/1", "job ReserveStock")]}
    assert meaning_errors(meaning, {"nodes": []}) == []
    meaning["relations"].append(rel(enqueue, queue, "job SendReceipt"))
    errors = meaning_errors(meaning, {"nodes": []})
    assert len(errors) == 1 and "relation 5 duplicates relation 1" in errors[0] and "job queue" in errors[0]


def test_a_service_must_cite_evidence(shop_repo):
    meaning = copy.deepcopy(MEANING)
    svc = next(n for n in meaning["nodes"] if n["id"] == "svc:shop")
    svc.pop("evidence")
    errors = mapcheck.check(built(shop_repo, meaning))
    assert any("svc:shop" in e and "evidence" in e for e in errors)
    lib = next(n for n in meaning["nodes"] if n["kind"] == "library")
    assert not lib.get("evidence") and not any(lib["id"] in e for e in errors)   # libraries stay optional


def test_a_wildcard_relation_can_list_its_concrete_tables(shop_repo):
    meaning = copy.deepcopy(MEANING)
    w = meaning["relations"][2]
    w["key"], w["to"] = "table public.*", "db:postgres:DB_HOST"
    w["tables"] = ["public.orders", "public.order_lines"]
    cmap = built(shop_repo, meaning)
    assert mapcheck.check(cmap) == []
    rel = next(r for r in cmap["relations"] if r.get("tables"))
    assert rel["tables"] == ["public.orders", "public.order_lines"]


def test_tables_need_a_wildcard_key_and_must_be_names(shop_repo):
    meaning = copy.deepcopy(MEANING)
    meaning["relations"][2]["tables"] = ["public.orders"]            # key is a single table
    assert any("tables" in e and "wildcard" in e for e in mapcheck.check(built(shop_repo, meaning)))
    meaning["relations"][2]["key"] = "table public.*"
    meaning["relations"][2]["tables"] = [3]
    assert any("tables" in e for e in mapcheck.check(built(shop_repo, meaning)))


def test_a_module_deployed_by_two_services_shows_a_twin(shop_repo):
    meaning = copy.deepcopy(MEANING)
    shop = next(n for n in meaning["nodes"] if n["id"] == "svc:shop")
    shop["modules"] = ["shop", "worker"]                 # worker's code is also baked into shop's image
    cmap = built(shop_repo, meaning)
    assert mapcheck.check(cmap) == []
    by_id = {n["id"]: n for n in cmap["nodes"]}
    roots = [n["id"] for n in cmap["nodes"] if n.get("parent") == "svc:worker" and n["kind"] == "package"]
    assert roots, "the code stays with the service whose primary (first-listed) module it is"
    assert by_id["svc:shop"]["twins"] == roots
    shop_floor = cmap["layout"]["containers"]["svc:shop"]["items"]
    assert all(f"twin:{r}" in shop_floor for r in roots)
    assert any("deployed by" in p["text"] and "twin" in p["text"] for p in cmap["problems"])


def test_a_twin_item_must_name_a_twin_of_its_service(shop_repo):
    cmap = built(shop_repo)
    cmap["layout"]["containers"]["svc:shop"]["items"]["twin:nope"] = {"region": "line", "col": 9, "row": 9}
    assert any("twin:nope" in e for e in mapcheck.check(cmap))


def test_a_twin_left_over_from_the_last_map_is_dropped(shop_repo):
    meaning = copy.deepcopy(MEANING)
    next(n for n in meaning["nodes"] if n["id"] == "svc:shop")["twins"] = ["worker::worker/"]   # carried by diff.py
    cmap = built(shop_repo, meaning)
    assert "twins" not in next(n for n in cmap["nodes"] if n["id"] == "svc:shop")
    assert mapcheck.check(cmap) == []


def test_the_owner_of_a_shared_module_does_not_depend_on_meaning_order(shop_repo):
    meaning = copy.deepcopy(MEANING)
    shop = next(n for n in meaning["nodes"] if n["id"] == "svc:shop")
    worker = next(n for n in meaning["nodes"] if n["id"] == "svc:worker")
    shop["modules"], worker["modules"] = ["shop", "scripts"], ["worker", "scripts"]   # neither lists scripts first
    lib = next(n for n in meaning["nodes"] if n["id"] == "lib:common")
    lib["modules"] = ["common", "pylib"]
    owners = []
    for order in (meaning["nodes"], list(reversed(meaning["nodes"]))):
        m = copy.deepcopy(meaning)
        m["nodes"] = copy.deepcopy(order)
        cmap = built(shop_repo, m)
        owners.append(next(n["parent"] for n in cmap["nodes"] if n["id"].startswith("scripts::") and n["kind"] == "package"))
    assert owners[0] == owners[1]


def test_a_shared_module_sits_under_the_deployed_service_not_the_hand_run_one(shop_repo):
    meaning = copy.deepcopy(MEANING)
    worker = next(n for n in meaning["nodes"] if n["id"] == "svc:worker")
    # a hand-run service, launched from a README line, whose id sorts before the deployed worker
    meaning["nodes"].append({"id": "svc:adhoc", "kind": "service", "name": "adhoc", "modules": list(worker["modules"][:1]),
                             "evidence": [{"file": "README.md", "line": 1}]})
    cmap = built(shop_repo, meaning)
    by_id = {n["id"]: n for n in cmap["nodes"]}
    roots = [n["id"] for n in cmap["nodes"] if n.get("parent") == "svc:worker" and n["kind"] == "package"]
    assert roots and by_id["svc:adhoc"]["twins"] == roots


def test_a_job_triggering_a_job_of_its_own_service_is_a_batch_relation(shop_repo):
    meaning = copy.deepcopy(MEANING)
    meaning["relations"].append({"kind": "batch", "from": "worker::worker.main#run/2", "to": "worker::worker.main#health/0",
                                 "key": "task health", "job": "health", "schedule": ["manual"],
                                 "confidence": "confirmed", "evidence": [{"file": "worker/main.py", "line": 1}]})
    st = structure.build(shop_repo, "docs/viz-code")
    assert meaning_errors(meaning, st) == []
    cmap = assemble(st, meaning)
    assert mapcheck.check(cmap) == []
    batch = [r for r in cmap["relations"] if r["kind"] == "batch"]
    assert [(r["from"], r["to"], r["key"]) for r in batch] == [
        ("worker::worker.main#run/2", "worker::worker.main#health/0", "task health")]
    # the target is an entry point like any batch target: it wants an example for its task key, nothing else
    assert [(w["id"], w["node"]) for w in mapcheck.warnings(cmap) if "health" in (w["node"] or "")] == [
        ("example.missing", "worker::worker.main#health/0")]


def test_one_call_through_two_library_methods_is_one_relation():
    rel = lambda via: {"kind": "request", "from": "svc:web", "to": "api::a.v#list/0", "key": "GET /charts",
                       "via": via, "confidence": "confirmed", "evidence": [{"file": "web/a.ts", "line": 3}]}
    errors = meaning_errors({"relations": [rel("lib::c#get/1"), rel("lib::c#fetch/1")]}, {"nodes": []})
    assert len(errors) == 1 and "two library methods (lib::c#get/1, lib::c#fetch/1)" in errors[0]
    assert "job queue" not in errors[0]


GO_TWO_SERVICES = {
    "go.mod": "module shop\n",
    "cmd/orders/main.go": 'package main\n\nimport "shop/internal/orders"\n\nfunc main() { orders.Run() }\n',
    "cmd/billing/main.go": 'package main\n\nimport "shop/internal/billing"\n\nfunc main() { billing.Run() }\n',
    "internal/orders/run.go": 'package orders\n\nimport "shop/pkg/log"\n\nfunc Run() { log.Info() }\n',
    "internal/orders/store/db.go": "package store\n\nfunc Save() {}\n",
    "internal/billing/run.go": "package billing\n\nfunc Run() {}\n",
    "pkg/log/log.go": "package log\n\nfunc Info() {}\n",
    "compose.yml": "services:\n  orders:\n    build: .\n  billing:\n    build: .\n",
}


def test_services_of_one_module_claim_their_packages(make_repo):
    s = structure.build(make_repo(GO_TWO_SERVICES))
    pk = {n["name"].strip("/"): n["id"] for n in s["nodes"] if n["kind"] == "package"}
    meaning = {"nodes": [
        {"id": "svc:orders", "kind": "service", "name": "orders", "modules": ["."],
         "packages": [pk["cmd/orders"], pk["internal/orders"]], "evidence": [{"file": "compose.yml", "line": 2}]},
        {"id": "svc:billing", "kind": "service", "name": "billing", "modules": ["."],
         "packages": [pk["cmd/billing"], pk["internal/billing"]], "evidence": [{"file": "compose.yml", "line": 4}]}],
        "relations": []}
    assert meaning_errors(meaning, s) == []
    cmap = assemble(s, copy.deepcopy(meaning))
    assert mapcheck.check(cmap) == []
    parent = {n["id"]: n.get("parent") for n in cmap["nodes"]}
    assert parent[pk["internal/orders"]] == parent[pk["internal/orders/store"]] == parent[pk["cmd/orders"]] == "svc:orders"
    assert parent[pk["internal/billing"]] == parent[pk["cmd/billing"]] == "svc:billing"
    # the shared package sits with the module's owner (the lowest id), a twin in the other
    by_id = {n["id"]: n for n in cmap["nodes"]}
    assert parent[pk["pkg/log"]] == "svc:billing" and by_id["svc:orders"]["twins"] == [pk["pkg/log"]]
    bad = copy.deepcopy(meaning)
    bad["nodes"][1]["packages"] = [pk["cmd/orders"], "nope"]
    bad["nodes"][0]["modules"] = []
    errors = meaning_errors(bad, s)
    assert any("no such package" in e for e in errors) and any("list that module" in e for e in errors)

    # a claiming service's calls into the shared code it does not own still resolve
    calls = {(r["from"], r["to"]) for r in cmap["relations"] if r["kind"] == "calls"}
    assert any(f.endswith("internal/orders/run.go#Run/0") and t.endswith("log.go#Info/0") for f, t in calls), calls


def test_a_claimed_package_takes_the_packages_below_it_in_python(make_repo):
    s = structure.build(make_repo({
        "shop/__init__.py": "", "shop/orders/__init__.py": "", "shop/orders/store/__init__.py": "",
        "shop/orders/store/db.py": "def save():\n    pass\n", "shop/billing/__init__.py": "",
        "shop/billing/run.py": "def run():\n    pass\n", "shop/orders/run.py": "def run():\n    pass\n"}))
    pk = {n["name"].strip("/"): n["id"] for n in s["nodes"] if n["kind"] == "package"}
    meaning = {"nodes": [
        {"id": "svc:orders", "kind": "service", "name": "orders", "modules": ["shop"], "packages": [pk["shop.orders"]],
         "evidence": [{"file": "shop/orders/run.py", "line": 1}]},
        {"id": "svc:billing", "kind": "service", "name": "billing", "modules": ["shop"],
         "packages": [pk["shop.billing"]], "evidence": [{"file": "shop/billing/run.py", "line": 1}]}], "relations": []}
    assert meaning_errors(meaning, s) == []
    parent = {n["id"]: n.get("parent") for n in assemble(s, copy.deepcopy(meaning))["nodes"]}
    assert parent[pk["shop.orders.store"]] == parent[pk["shop.orders"]] == "svc:orders"
