"""Airflow project `forecast` (service: demand-forecast).

Nightly: have the *features* project refresh the zone features, turn them
into a demand index per zone and hour, and write demand_forecast in Postgres,
which the pricing service reads when it quotes.
"""
import os
from datetime import datetime

import psycopg
from airflow.decorators import dag, task
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

from pipelines_shared.warehouse import read_frame, table
from pipelines_shared.zone_math import to_demand_index


@dag(
    dag_id="demand_forecast",
    schedule="30 1 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["postgres"],
)
def demand_forecast():
    # zone_features belongs to the features project (service feature-store); wait for a fresh run of it
    refresh_features = TriggerDagRunOperator(
        task_id="refresh_zone_features",
        trigger_dag_id="zone_features",
        conf={"days": 28},
        wait_for_completion=True,
        poke_interval=60,
    )

    @task
    def history_check() -> int:
        """Sanity input: how many bay events landed in the last week."""
        frame = read_frame(f"SELECT COUNT(*) AS n FROM {table('bay_events')} WHERE observed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)")
        return int(frame["n"][0])

    @task
    def write_forecast(recent_events: int) -> int:
        if recent_events == 0:
            raise ValueError("no recent sensor data; refusing to overwrite the forecast")
        features = read_frame(f"SELECT zone_id, hour_of_day, occupancy FROM {table('zone_features')}")
        forecast = to_demand_index(features)
        with psycopg.connect(
            host=os.environ["DB_HOST"],
            dbname=os.environ.get("DB_NAME", "parking"),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
        ) as conn:
            for row in forecast.itertuples():
                conn.execute(
                    """
                    INSERT INTO demand_forecast (zone_id, hour_of_day, demand_index)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (zone_id, hour_of_day) DO UPDATE SET demand_index = EXCLUDED.demand_index
                    """,
                    (row.zone_id, int(row.hour_of_day), float(row.demand_index)),
                )
        return len(forecast)

    refresh_features >> write_forecast(recent_events=history_check())


demand_forecast()
