from datetime import datetime

from airflow.decorators import dag, task

from _common import pg


@dag(
    dag_id="zone_utilisation_hourly",
    schedule="5 * * * *",  # every hour at :05, so 24 runs a day
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=["postgres"],
)
def zone_utilisation_hourly():
    @task
    def refresh_today() -> None:
        with pg() as conn:
            conn.execute(
                """
                INSERT INTO zone_utilisation (day, zone_id, utilisation)
                SELECT current_date, zone_id, avg(CASE WHEN occupied THEN 1.0 ELSE 0.0 END)
                FROM bay_status
                GROUP BY zone_id
                ON CONFLICT (day, zone_id) DO UPDATE SET utilisation = EXCLUDED.utilisation
                """
            )

    refresh_today()


zone_utilisation_hourly()
