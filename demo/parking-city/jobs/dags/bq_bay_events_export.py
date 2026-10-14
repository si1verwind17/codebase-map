from datetime import datetime

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
