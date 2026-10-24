from conftest import SHOP

from vizcode import ids
from vizcode.adapters import python as py

WORKER = {"id": "mod:worker", "path": "worker", "lang": "python", "build": "python-package"}
SCRIPTS = {"id": "mod:scripts", "path": "scripts", "lang": "python", "build": "python-scripts"}


def by_id(res):
    return {n["id"]: n for n in res["nodes"]}


def test_python_nodes_ids_and_signatures():
    res = py.parse(SHOP["worker/main.py"].encode(), "worker/main.py", WORKER, ids.IdRegistry())
    n = by_id(res)
    assert res["package"] == "worker"
    assert n["worker::worker.main"]["kind"] == "file"
    assert n["worker::worker.main"]["parent"] == "worker::worker/"
    run = n["worker::worker.main#run/2"]
    assert run["signature"] == {"params": [{"name": "job_id", "type": "str"}, {"name": "dry", "type": "bool", "optional": True}],
                                "returns": "dict"}
    store = n["worker::worker.main.Job#store/3"]
    assert store["parent"] == "worker::worker.main.Job"
    assert [p["name"] for p in store["signature"]["params"]] == ["conn", "*args", "**kw"]
    assert n["worker::worker.main.Job#_secret/0"]["visibility"] == "private"
    assert n["worker::worker.main.Job#__init__/1"]["visibility"] == "public"
    assert n["worker::worker.main.Job"]["metrics"]["methods"] == 3
    # a second `run` with the same arity is kept, not overwritten
    assert "worker::worker.main#run/1" in n


def test_python_duplicate_ids_get_suffix():
    src = b"def f(a):\n    pass\n\n\ndef f(b):\n    pass\n"
    res = py.parse(src, "worker/dup.py", WORKER, ids.IdRegistry())
    assert {"worker::worker.dup#f/1", "worker::worker.dup#f/1~2"} <= set(by_id(res))


def test_python_facts():
    res = py.parse(SHOP["worker/main.py"].encode(), "worker/main.py", WORKER, ids.IdRegistry())
    assert {(r["method"], r["path"]) for r in res["routes"]} == {("POST", "/v1/work/run/{job_id}"), ("GET", "/health")}
    assert next(r for r in res["routes"] if r["path"] == "/health")["handler"] == "worker::worker.main#health/0"
    imports = {i["target"]: i["relative"] for i in res["imports"]}
    assert imports == {"os": False, "requests": False, "fastapi": False, ".util.helpers": True}
    assert [e["key"] for e in res["env_keys"]] == ["SHOP_URL"]
    texts = [s["text"] for s in res["strings"]]
    assert "INSERT INTO public.jobs (name) VALUES (%s)" in texts  # implicit concatenation joined
    call = next(c for c in res["calls"] if c["callee"] == "requests.post")
    assert call["in"] == "worker::worker.main#run/2"


def test_python_loose_script_and_syntax_error():
    res = py.parse(b"def main(:\n    pass\n", "scripts/run_once.py", SCRIPTS, ids.IdRegistry())
    assert res["parse_error"] is True
    assert by_id(res)["scripts::scripts.run_once"]["parent"] == "scripts::scripts/"


def test_python_routes_nested_in_app_factory():
    src = (b"from fastapi import FastAPI\n\n\ndef create_app(cfg) -> FastAPI:\n"
           b"    app = FastAPI(title=f\"svc ({cfg})\")\n\n    @app.post(\"/v1/invoke\")\n"
           b"    async def invoke(event):\n        return event\n\n    return app\n")
    res = py.parse(src, "worker/app.py", WORKER, ids.IdRegistry())
    assert res["routes"] == [{"method": "POST", "path": "/v1/invoke", "handler": "worker::worker.app#create_app/1",
                              "line": 8, "framework": "fastapi", "router": "app", "nested_handler": "invoke"}]


def test_a_latin1_file_keeps_its_accented_identifiers():
    src = 'Q = "select * from t\xe9 where x"\n'.encode("latin-1")
    res = py.parse(src, "worker/q.py", WORKER, ids.IdRegistry())
    assert any("from té where" in (s["text"] if isinstance(s, dict) else s) for s in res["strings"])


# --- Airflow TaskFlow DAGs (as in the parking-city demo), Flyte workflows -----
JOBS = {"id": "mod:jobs/dags", "path": "jobs/dags", "lang": "python", "build": "python-scripts"}
FORECAST = {"id": "mod:forecast", "path": "forecast", "lang": "python", "build": "python-scripts"}

BQ_BAY_EVENTS = '''from datetime import datetime

from airflow.decorators import dag, task

from _common import bq, bq_table, pg


@dag(
    dag_id="bq_bay_events_export",
    schedule="*/15 * * * *",  # every 15 minutes
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["bigquery"],
)
def bq_bay_events_export():
    @task
    def export_snapshot() -> int:
        with pg() as conn:
            rows = conn.execute("SELECT zone_id, bay_id, occupied, since FROM bay_status").fetchall()
        payload = [
            {"zone_id": z, "bay_id": b, "occupied": o, "since": s.isoformat()} for z, b, o, s in rows
        ]
        errors = bq().insert_rows_json(bq_table("bay_snapshots"), payload)
        if errors:
            raise RuntimeError(errors)
        return len(payload)

    export_snapshot()


bq_bay_events_export()
'''

FORECAST_WF = '''import os

import pandas as pd
import psycopg
from flytekit import task, workflow, reference_task, CronSchedule, LaunchPlan

from pipelines_shared.warehouse import read_frame, table
from pipelines_shared.zone_math import to_demand_index


@reference_task(
    project="features",
    domain="production",
    name="workflows.compute_zone_features",
    version=os.environ.get("FEATURES_VERSION", "latest"),
)
def compute_zone_features(days: int) -> str:
    """Task owned by the features project; runs there, returns the table name."""
    ...


@task
def load_features(features_table: str) -> pd.DataFrame:
    return read_frame(f"SELECT zone_id, hour_of_day, occupancy FROM `{features_table}`")


@workflow
def forecast_wf(days: int = 28) -> int:
    features_table = compute_zone_features(days=days)
    return load_features(features_table=features_table)


nightly = LaunchPlan.get_or_create(
    forecast_wf,
    name="forecast_nightly",
    schedule=CronSchedule(schedule="30 1 * * *"),
    default_inputs={"days": 28},
)
'''


def test_nested_airflow_tasks_are_methods_of_the_file():
    res = py.parse(BQ_BAY_EVENTS.encode(), "jobs/dags/bq_bay_events_export.py", JOBS, ids.IdRegistry())
    n = by_id(res)
    fid = "jobs/dags::dags.bq_bay_events_export"
    task_ = n[f"{fid}#export_snapshot/0"]
    assert task_["parent"] == fid and task_["line"] == 18
    assert task_["signature"] == {"params": [], "returns": "int"}
    assert n[fid]["metrics"]["methods"] == 2
    ins = {c["callee"]: c["in"] for c in res["calls"]}
    assert ins["conn.execute"] == f"{fid}#export_snapshot/0"       # calls inside the task belong to it
    assert ins["export_snapshot"] == f"{fid}#bq_bay_events_export/0"


def test_nested_task_name_clashing_with_a_top_level_function_is_qualified():
    src = (b"from airflow import DAG\nfrom airflow.decorators import dag, task\n\n\n"
           b"def extract():\n    return 1\n\n\n"
           b"@dag(schedule=None)\ndef etl():\n    @task\n    def extract():\n        return 2\n\n"
           b"    @task\n    def load(x):\n        return x\n\n    load(extract())\n\n\n"
           b"with DAG(\"legacy\", schedule_interval=\"@daily\") as d:\n"
           b"    def push(rows):\n        return rows\n\n"
           b"    PythonOperator(task_id=\"push_rows\", python_callable=push)\n")
    res = py.parse(src, "jobs/dags/etl.py", JOBS, ids.IdRegistry())
    n = by_id(res)
    fid = "jobs/dags::dags.etl"
    assert {f"{fid}#extract/0", f"{fid}#etl.extract/0", f"{fid}#load/1", f"{fid}#push/1"} <= set(n)
    assert n[f"{fid}#etl.extract/0"]["name"] == "extract"
    assert res["dags"] == [
        {"framework": "airflow", "id": "etl", "schedule": "None", "tasks": ["extract", "load"],
         "node": f"{fid}#etl/0", "line": 9},
        {"framework": "airflow", "id": "legacy", "schedule": "@daily", "tasks": ["push_rows"],
         "node": fid, "line": 22},
    ]


def test_dag_id_and_schedule_facts():
    res = py.parse(BQ_BAY_EVENTS.encode(), "jobs/dags/bq_bay_events_export.py", JOBS, ids.IdRegistry())
    assert res["dags"] == [{"framework": "airflow", "id": "bq_bay_events_export", "schedule": "*/15 * * * *",
                            "tasks": ["export_snapshot"],
                            "node": "jobs/dags::dags.bq_bay_events_export#bq_bay_events_export/0", "line": 8}]


def test_flyte_launch_plans_and_reference_tasks():
    res = py.parse(FORECAST_WF.encode(), "forecast/workflows.py", FORECAST, ids.IdRegistry())
    fid = "forecast::forecast.workflows"
    assert res["workflows"] == [{"framework": "flyte", "id": "forecast_wf", "node": f"{fid}#forecast_wf/1",
                                 "line": 27, "launch_plans": [{"name": "forecast_nightly",
                                                               "schedule": "30 1 * * *", "line": 33}]}]
    assert res["reference_tasks"] == [{"kind": "task", "project": "features", "domain": "production",
                                       "name": "workflows.compute_zone_features",
                                       "node": f"{fid}#compute_zone_features/1", "line": 11}]
    assert res["dags"] == []


def test_dag_and_flyte_facts_in_summary(make_repo):
    from vizcode import structure
    repo = make_repo({"jobs/dags/bq_bay_events_export.py": BQ_BAY_EVENTS,
                      "forecast/workflows.py": FORECAST_WF})
    md = structure.summary_md(structure.build(repo))
    assert ("- **dags:** bq_bay_events_export schedule `*/15 * * * *` tasks [export_snapshot] → "
            "jobs/dags::dags.bq_bay_events_export#bq_bay_events_export/0 "
            "(jobs/dags/bq_bay_events_export.py:8)") in md
    assert ("- **flyte workflows:** forecast_wf launch plan forecast_nightly `30 1 * * *` → "
            "forecast::forecast.workflows#forecast_wf/1 (forecast/workflows.py:27)") in md
    assert ("- **reference tasks:** task project=features domain=production name=workflows.compute_zone_features → "
            "forecast::forecast.workflows#compute_zone_features/1 (forecast/workflows.py:11)") in md


def test_with_dag_prefix_is_a_plain_dag_id_else_the_alias_else_numbered():
    src = (b"import os\nfrom airflow import DAG\n\n\n"
           b"def push(rows):\n    return rows\n\n\n"
           b"with DAG(dag_id=f\"{os.environ['ENV']} load\") as load_dag:\n"
           b"    def push(rows):\n        return rows\n\n\n"
           b"with DAG(dag_id=os.environ['DAG']):\n"
           b"    def push(rows):\n        return rows\n\n\n"
           b"with DAG(\"nightly\") as d:\n"
           b"    def push(rows):\n        return rows\n")
    res = py.parse(src, "jobs/dags/load.py", JOBS, ids.IdRegistry())
    fid = "jobs/dags::dags.load"
    assert {f"{fid}#push/1", f"{fid}#load_dag.push/1", f"{fid}#DAG2.push/1", f"{fid}#nightly.push/1"} <= set(by_id(res))
    assert [d["id"] for d in res["dags"]] == ["f\"{os.environ['ENV']} load\"", "os.environ['DAG']", "nightly"]
