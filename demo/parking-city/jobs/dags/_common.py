"""Small helpers shared by the DAGs: one place that knows where Postgres,
BigQuery and the receipts bucket are (all from environment variables set on
the Airflow workers)."""
import os

import boto3
import httpx
import psycopg
from google.cloud import bigquery


def pg() -> psycopg.Connection:
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        dbname=os.environ.get("DB_NAME", "parking"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )


def bq() -> bigquery.Client:
    return bigquery.Client(project=os.environ["BQ_PROJECT"])


def bq_table(name: str) -> str:
    return f"{os.environ['BQ_PROJECT']}.analytics.{name}"


def s3_put(key: str, body: bytes) -> None:
    boto3.client("s3").put_object(Bucket=os.environ["RECEIPTS_BUCKET"], Key=key, Body=body)


def billing_post(path: str) -> dict:
    """POST to the billing service; its base URL is BILLING_URL."""
    resp = httpx.post(f"{os.environ['BILLING_URL']}{path}", timeout=120.0)
    resp.raise_for_status()
    return resp.json()
