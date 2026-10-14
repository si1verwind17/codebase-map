from datetime import datetime

from airflow.decorators import dag, task

from _common import pg
from pg_revenue_correction import SUBTRACT_REFUNDS


@dag(
    dag_id="daily_revenue_rollup",
    schedule="30 2 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["postgres"],
)
def daily_revenue_rollup():
    @task
    def rollup(ds=None) -> None:
        with pg() as conn:
            conn.execute(
                """
                INSERT INTO daily_revenue (day, zone_id, cents)
                SELECT date(r.starts_at), r.zone_id, sum(i.cents)
                FROM invoices i JOIN reservations r ON r.id::text = i.reservation_id
                WHERE i.status = 'PAID' AND date(r.starts_at) = %s
                GROUP BY date(r.starts_at), r.zone_id
                ON CONFLICT (day, zone_id) DO UPDATE SET cents = EXCLUDED.cents
                """,
                (ds,),
            )
            conn.execute(SUBTRACT_REFUNDS)

    rollup()


daily_revenue_rollup()
