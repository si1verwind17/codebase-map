import pandas as pd


def hourly_occupancy(events: pd.DataFrame) -> pd.DataFrame:
    """Average occupied share per zone and hour of day from raw bay snapshots."""
    events = events.assign(hour_of_day=pd.to_datetime(events["observed_at"]).dt.hour)
    grouped = events.groupby(["zone_id", "hour_of_day"])["occupied"].mean()
    return grouped.rename("occupancy").reset_index()


def to_demand_index(occupancy: pd.DataFrame) -> pd.DataFrame:
    """Scales occupancy so that 1.0 means 'a normal hour' for that zone."""
    mean = occupancy.groupby("zone_id")["occupancy"].transform("mean").clip(lower=0.01)
    return occupancy.assign(demand_index=(occupancy["occupancy"] / mean).clip(0.5, 2.0))
