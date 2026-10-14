import json
from datetime import datetime

from airflow.decorators import dag, task

from _common import pg, s3_put


@dag(
    dag_id="s3_audit_export",
    schedule="0 4 * * 1",  # weekly, Monday 04:00
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["s3"],
)
def s3_audit_export():
    @task
    def export_payments(ds=None) -> str:
        with pg() as conn:
            rows = conn.execute(
                "SELECT id, payment_intent_id, status, amount_cents FROM payments "
                "WHERE received_at > now() - interval '7 days'"
            ).fetchall()
        key = f"exports/audit/payments-{ds}.json"
        s3_put(key, json.dumps(rows).encode("utf-8"))
        return key

    export_payments()


s3_audit_export()
