from datetime import datetime

from airflow.decorators import dag, task

from _common import billing_post


@dag(
    dag_id="nightly_settlement",
    schedule="0 2 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["billing"],
)
def nightly_settlement():
    @task
    def settle() -> int:
        # Closes every paid invoice of the day; billing owns the invoices table.
        return billing_post("/internal/settle")["settled"]

    settle()


nightly_settlement()
