import csv
import io
from datetime import datetime

from airflow.decorators import dag, task

from _common import pg, s3_put


@dag(
    dag_id="s3_invoice_export",
    schedule="15 4 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["s3"],
)
def s3_invoice_export():
    @task
    def export_csv(ds=None) -> str:
        with pg() as conn:
            rows = conn.execute(
                "SELECT id, reservation_id, driver_id, cents, status FROM invoices WHERE date(settled_at) = %s",
                (ds,),
            ).fetchall()
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        key = f"exports/invoices/{ds}.csv"
        s3_put(key, buf.getvalue().encode("utf-8"))
        return key

    export_csv()


s3_invoice_export()
