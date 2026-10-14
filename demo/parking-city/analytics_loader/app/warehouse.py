from google.cloud import bigquery

from common_py.config import env


class BayEventsTable:
    """Append-only table analytics.bay_events in the BigQuery project BQ_PROJECT."""

    def __init__(self) -> None:
        project = env("BQ_PROJECT")
        self._client = bigquery.Client(project=project)
        self._table = f"{project}.analytics.bay_events"

    def insert(self, rows: list[dict]) -> list:
        shaped = [
            {
                "zone_id": r["zone_id"],
                "bay_id": r["bay_id"],
                "occupied": r["occupied"],
                "plate": r.get("plate") or None,
                "observed_at": r["observed_at_ms"] / 1000,
            }
            for r in rows
        ]
        return self._client.insert_rows_json(self._table, shaped)
