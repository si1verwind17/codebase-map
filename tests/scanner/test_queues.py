"""The queues group of the packs and stack.yaml: in-process queue creation sites, per-file facts, summary line,
and the audit warning for a creation site the map does not account for."""
import copy

import pytest
from conftest import commit_all, with_stack
from meaning_fixture import MEANING

from vizcode import mapcheck, stack, structure
from vizcode.assemble import assemble

from helpers import write

ZQ = "scala:\n  queues:\n    - {name: zq, when: acme.mq, delivery: queue, regex: '\\bMailbox\\.make\\b'}\n"


def test_find_queues_reports_line_enclosing_method_and_delivery(tmp_path):
    st = stack.load(write(tmp_path, ZQ))
    src = "object M {\n  def make = for {\n    q <- Mailbox.make[Int](100)\n  } yield q\n}\n"
    got = stack.find_queues(st, "scala", src, ["acme.mq.Mailbox"], [(2, 4, "M#make/0")], "file")
    assert got == [{"line": 3, "in": "M#make/0", "delivery": "queue", "pattern": "zq", "source": "stack.yaml"}]
    assert stack.find_queues(st, "scala", src, [], [(2, 4, "M#make/0")], "file") == []   # `when` not imported


@pytest.mark.parametrize("text,expect", [
    ("scala:\n  queues:\n    - {name: q, regex: 'x'}\n", "scala.queues[0] (q): delivery must be queue or fan-out"),
    ("scala:\n  queues:\n    - {name: q, regex: 'x', delivery: topic}\n", "delivery must be queue or fan-out"),
    ("scala:\n  queues:\n    - {regex: 'x', delivery: queue}\n", "scala.queues[0]: missing name"),
    ("scala:\n  queues:\n    - {name: q, regex: 'x', delivery: queue, table: t}\n", "unknown key 'table'"),
])
def test_bad_queue_entries(tmp_path, text, expect):
    with pytest.raises(stack.StackError) as e:
        stack.load(write(tmp_path, text))
    assert expect in str(e.value)


@pytest.mark.parametrize("lang,src", [
    ("scala", "import zio._\nobject A { def m = Queue.bounded[Int](8) }\n"),
    ("scala", "import zio._\nobject A { def m = Hub.unbounded[Int] }\n"),
    ("go", "package a\nfunc m() { c := make(chan int, 4); _ = c }\n"),
    ("python", "import asyncio\nasync def m():\n    q = asyncio.Queue()\n"),
    ("kotlin", "import kotlinx.coroutines.channels.Channel\nfun m() { val c = Channel<Int>(4) }\n"),
    ("java", "import java.util.concurrent.LinkedBlockingQueue;\nclass A { void m() { var q = new LinkedBlockingQueue<String>(); } }\n"),
    ("csharp", "using System.Threading.Channels;\nclass A { void M() { var c = Channel.CreateBounded<int>(4); } }\n"),
    ("rust", "use tokio::sync::mpsc;\nfn m() { let (tx, rx) = mpsc::channel(8); }\n"),
])
def test_built_in_packs_find_common_creation_sites(lang, src):
    st = stack.default()
    imports = {"scala": ["zio"], "go": [], "python": ["asyncio"], "kotlin": ["kotlinx.coroutines.channels.Channel"],
               "java": ["java.util.concurrent.LinkedBlockingQueue"], "csharp": ["System.Threading.Channels"],
               "rust": ["tokio::sync::mpsc"]}[lang]
    assert stack.find_queues(st, lang, src, imports, [], "f"), (lang, src)


def test_built_in_packs_skip_lookalikes():
    st = stack.default()
    assert stack.find_queues(st, "scala", "object A { val q = Queue(1, 2) }\n", ["scala.collection"], [], "f") == []
    assert stack.find_queues(st, "python", "from collections import deque\nq = deque()\n", ["collections"], [], "f") == []


def queue_repo(make_repo):
    from conftest import SHOP
    files = dict(SHOP)
    files["worker/jobs.py"] = "import asyncio\n\n\ndef make():\n    return asyncio.Queue()\n"
    return make_repo(files)


def test_facts_summary_and_audit_warning(make_repo):
    repo = queue_repo(make_repo)
    s = structure.build(repo, "docs/viz-code")
    assert s["facts"]["worker/jobs.py"]["queues"] == [
        {"line": 5, "in": "worker::worker.jobs#make/0", "delivery": "queue", "pattern": "asyncio-queue",
         "source": "pack"}]
    md = structure.summary_md(s)
    assert "- **in-process queues:** queue at worker/jobs.py:5 in make" in md
    cmap = assemble(s, copy.deepcopy(MEANING))
    warned = [w for w in mapcheck.warnings(cmap, md) if w["id"] == "queue.missing"]
    assert len(warned) == 1 and "worker/jobs.py:5" in warned[0]["detail"]

    m = copy.deepcopy(MEANING)       # a queue node citing the line accounts for it
    m["nodes"].append({"id": "inq:worker:jobs", "kind": "in-process-queue", "parent": "svc:worker", "name": "jobs",
                       "delivery": "queue", "evidence": [{"file": "worker/jobs.py", "line": 5}]})
    assert not [w for w in mapcheck.warnings(assemble(s, m), md) if w["id"] == "queue.missing"]

    m = copy.deepcopy(MEANING)       # so does a problem saying why it is none (one method fills and drains it)
    m["problems"].append({"text": "worker/jobs.py:5 is a local work buffer, no hand-off between methods",
                          "nodes": ["svc:worker"], "source": "agent"})
    assert not [w for w in mapcheck.warnings(assemble(s, m), md) if w["id"] == "queue.missing"]


def test_stack_yaml_adds_a_queue_pattern(make_repo):
    repo = queue_repo(make_repo)
    with_stack(repo, "python:\n  queues:\n    - {name: bus, delivery: fan-out, regex: '\\bEventBus\\(\\)'}\n")
    (repo / "worker/bus.py").write_text("def make():\n    return EventBus()\n")
    commit_all(repo)
    s = structure.build(repo, "docs/viz-code")
    assert s["facts"]["worker/bus.py"]["queues"][0]["delivery"] == "fan-out"
    assert "- python bus (stack.yaml): 1 queue in 1 file" in structure.summary_md(s)
