import os

import pandas as pd
from google.cloud import bigquery


def client() -> bigquery.Client:
    return bigquery.Client(project=os.environ["BQ_PROJECT"])


def read_frame(sql: str) -> pd.DataFrame:
    """Runs a query against the analytics dataset and returns a DataFrame."""
    return client().query(sql).to_dataframe()


def table(name: str) -> str:
    return f"`{os.environ['BQ_PROJECT']}.analytics.{name}`"
