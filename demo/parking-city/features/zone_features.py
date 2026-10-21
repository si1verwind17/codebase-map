"""Airflow project `features` (service: feature-store).

Builds per-zone hourly occupancy features from BigQuery and writes them back
to the analytics dataset for other projects to consume. The `forecast`
project triggers this DAG before it forecasts.
"""
from datetime import datetime

from airflow.decorators import dag, task

from pipelines_shared.warehouse import client, read_frame, table
from pipelines_shared.zone_math import hourly_occupancy


@dag(
    dag_id="zone_features",
    schedule="0 1 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    params={"days": 28},
    tags=["bigquery"],
)
def zone_features():
    @task
    def compute_zone_features(params=None) -> str:
        """Reads bay_events, aggregates to zone x hour, writes analytics.zone_features."""
        days = int(params["days"])
        events = read_frame(
            f"""
            SELECT zone_id, occupied, observed_at
            FROM {table('bay_events')}
            WHERE observed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
            """
        )
        features = hourly_occupancy(events)
        job = client().load_table_from_dataframe(
            features,
            table("zone_features").strip("`"),
        )
        job.result()
        return table("zone_features").strip("`")

    compute_zone_features()


zone_features()
