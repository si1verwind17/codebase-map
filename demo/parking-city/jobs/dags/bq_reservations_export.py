from datetime import datetime

from airflow.decorators import dag, task

from _common import bq, bq_table, pg


@dag(
    dag_id="bq_reservations_export",
    schedule="0 * * * *",  # hourly
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["bigquery"],
)
def bq_reservations_export():
    @task
    def export_recent() -> int:
        with pg() as conn:
            rows = conn.execute(
                "SELECT id, zone_id, status, quote_cents, starts_at FROM reservations "
                "WHERE starts_at > now() - interval '2 hours'"
            ).fetchall()
        payload = [
            {"id": str(i), "zone_id": z, "status": s, "quote_cents": c, "starts_at": t.isoformat()}
            for i, z, s, c, t in rows
        ]
        if payload:
            bq().insert_rows_json(bq_table("reservations"), payload)
        return len(payload)

    export_recent()


bq_reservations_export()
