"""Flyte project `forecast` (service: demand-forecast).

Nightly: pull zone features (computed by the *features* project), turn them
into a demand index per zone and hour, and write demand_forecast in Postgres,
which the pricing service reads when it quotes.
"""
import os

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


@task
def history_check() -> int:
    """Sanity input: how many bay events landed in the last week."""
    frame = read_frame(f"SELECT COUNT(*) AS n FROM {table('bay_events')} WHERE observed_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)")
    return int(frame["n"][0])


@task
def write_forecast(features: pd.DataFrame, recent_events: int) -> int:
    if recent_events == 0:
        raise ValueError("no recent sensor data; refusing to overwrite the forecast")
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


@workflow
def forecast_wf(days: int = 28) -> int:
    features_table = compute_zone_features(days=days)
    return write_forecast(
        features=load_features(features_table=features_table),
        recent_events=history_check(),
    )


nightly = LaunchPlan.get_or_create(
    forecast_wf,
    name="forecast_nightly",
    schedule=CronSchedule(schedule="30 1 * * *"),
    default_inputs={"days": 28},
)
