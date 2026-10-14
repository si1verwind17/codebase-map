from datetime import datetime

from airflow.decorators import dag, task

from _common import bq, bq_table, pg


@dag(
    dag_id="bq_revenue_export",
    schedule="45 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["bigquery"],
)
def bq_revenue_export():
    @task
    def export_day(ds=None) -> int:
        with pg() as conn:
            rows = conn.execute(
                "SELECT zone_id, cents FROM daily_revenue WHERE day = %s", (ds,)
            ).fetchall()
        payload = [{"day": ds, "zone_id": z, "cents": c} for z, c in rows]
        if payload:
            bq().insert_rows_json(bq_table("daily_revenue"), payload)
        return len(payload)

    export_day()


bq_revenue_export()
