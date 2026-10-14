from datetime import datetime

from airflow.decorators import dag, task

from _common import bq, bq_table, pg


@dag(
    dag_id="bq_tariff_snapshot",
    schedule="0 1 * * 1",  # Mondays 01:00
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["bigquery"],
)
def bq_tariff_snapshot():
    @task
    def snapshot() -> int:
        with pg() as conn:
            rows = conn.execute(
                "SELECT zone_id, cents_per_hour, currency FROM tariffs WHERE active"
            ).fetchall()
        payload = [{"zone_id": z, "cents_per_hour": c, "currency": cur} for z, c, cur in rows]
        bq().insert_rows_json(bq_table("tariff_history"), payload)
        return len(payload)

    snapshot()


bq_tariff_snapshot()
