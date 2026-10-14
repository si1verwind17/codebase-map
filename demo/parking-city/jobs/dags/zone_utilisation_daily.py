from datetime import datetime

from airflow.decorators import dag, task

from _common import pg


@dag(
    dag_id="zone_utilisation_daily",
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["postgres"],
)
def zone_utilisation_daily():
    @task
    def compute(ds=None) -> None:
        with pg() as conn:
            conn.execute(
                """
                INSERT INTO zone_utilisation (day, zone_id, utilisation)
                SELECT %s::date, zone_id, avg(CASE WHEN occupied THEN 1.0 ELSE 0.0 END)
                FROM bay_status
                GROUP BY zone_id
                ON CONFLICT (day, zone_id) DO UPDATE SET utilisation = EXCLUDED.utilisation
                """,
                (ds,),
            )

    compute()


zone_utilisation_daily()
