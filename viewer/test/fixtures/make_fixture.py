#!/usr/bin/env python3
"""Regenerate shop.code-map.json from the scanner's own test fixture repo.

Run from skills/visualizing-codebases/scripts with the skill's venv:
  $PY ../viewer/test/fixtures/make_fixture.py
Adds a stream, a topic event pair and an external to the scanner fixture's meaning so every
line kind the viewer draws is covered.
"""
import copy
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[2] / "skills" / "visualizing-codebases" / "scripts"
sys.path[:0] = [str(SCRIPTS), str(HERE.parents[2] / "tests")]

from conftest import GIT_ENV, SHOP  # noqa: E402
from meaning_fixture import MEANING  # noqa: E402

from vizcode import mapcheck, structure  # noqa: E402
from vizcode.assemble import assemble  # noqa: E402

EXTRA_NODES = [{"id": "3p:feed", "kind": "external", "name": "price feed"},
               {"id": "topic:kafka:orders", "kind": "topic", "name": "orders", "delivery": "fan-out",
                "evidence": [{"file": "worker/main.py", "line": 12}]},
               {"id": "topic:kafka:orders.dlq", "kind": "topic", "name": "orders.dlq",
                "dead_letter_of": "topic:kafka:orders",
                "evidence": [{"file": "worker/main.py", "line": 14}]},
               {"id": "db:redis:REDIS_URL", "kind": "datastore", "name": "redis"}]
EXTRA_RELATIONS = [
    {"kind": "stream", "from": "svc:worker", "to": "3p:feed", "key": "wss://feed.example/prices", "data": "back",
     "confidence": "confirmed", "evidence": [{"file": "worker/main.py", "line": 6}]},
    {"kind": "event", "from": "shop::io.demo.shop.repo.PgOrderRepo#save/2", "to": "topic:kafka:orders", "key": "orders",
     "confidence": "inferred", "why": "publisher wiring is config-driven",
     "evidence": [{"file": "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala", "line": 11}]},
    {"kind": "event", "from": "topic:kafka:orders", "to": "worker::worker.main#run/2", "key": "orders",
     "confidence": "confirmed", "group": "worker", "evidence": [{"file": "worker/main.py", "line": 12}]},
    {"kind": "event", "from": "worker::worker.main#run/2", "to": "topic:kafka:orders.dlq", "key": "orders.dlq",
     "confidence": "confirmed", "on_failure": True, "evidence": [{"file": "worker/main.py", "line": 14}]},
    {"kind": "db-read", "from": "shop::io.demo.shop.repo.PgOrderRepo#save/2", "to": "db:redis:REDIS_URL",
     "key": "cache orders", "confidence": "confirmed",
     "evidence": [{"file": "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala", "line": 11}]},
    {"kind": "db-write", "from": "shop::io.demo.shop.repo.PgOrderRepo#save/2", "to": "db:redis:REDIS_URL",
     "key": "cache orders", "confidence": "confirmed",
     "evidence": [{"file": "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala", "line": 11}]},
    {"kind": "batch", "from": "svc:worker", "to": "svc:shop", "key": "nightly export", "confidence": "confirmed",
     "schedule": ["0 2 * * *"], "job": "nightly_export", "evidence": [{"file": "worker/main.py", "line": 6}]},
]


def main() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d) / "demo"
        repo.mkdir()
        git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, env=GIT_ENV)  # noqa: E731
        git("init", "-q", "-b", "main")
        for rel, content in SHOP.items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        git("add", "-A")
        git("commit", "-qm", "init")
        meaning = copy.deepcopy(MEANING)
        meaning["nodes"] += EXTRA_NODES
        for n in meaning["nodes"]:
            if n["id"] == "svc:worker":
                n["replicas"] = 2
        meaning["relations"] += EXTRA_RELATIONS
        cmap = assemble(structure.build(repo, "docs/viz-code"), meaning)
    errors = mapcheck.check(cmap)
    if errors:
        raise SystemExit("\n".join(errors))
    (HERE / "shop.code-map.json").write_text(json.dumps(cmap, indent=1) + "\n")
    print(f"wrote {HERE / 'shop.code-map.json'}: {len(cmap['nodes'])} nodes")


if __name__ == "__main__":
    main()
