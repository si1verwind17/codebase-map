"""Flyte project `features` (service: feature-store).

Builds per-zone hourly occupancy features from BigQuery and writes them back
to the analytics dataset for other projects to consume.
"""
from datetime import timedelta

from flytekit import task, workflow, CronSchedule, LaunchPlan

from pipelines_shared.warehouse import client, read_frame, table
from pipelines_shared.zone_math import hourly_occupancy


@task
def compute_zone_features(days: int) -> str:
    """Reads bay_events, aggregates to zone x hour, writes analytics.zone_features."""
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


@workflow
def features_wf(days: int = 28) -> str:
    return compute_zone_features(days=days)


nightly = LaunchPlan.get_or_create(
    features_wf,
    name="features_nightly",
    schedule=CronSchedule(schedule="0 1 * * *"),
    default_inputs={"days": 28},
)
