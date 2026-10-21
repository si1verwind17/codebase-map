# jobs: nightly-jobs (Airflow 2)

One Airflow project, registered as the service `nightly-jobs`. Ten DAGs in
`dags/`, each a TaskFlow DAG with a cron `schedule`, going to four destinations:

| DAG | schedule | destination |
|---|---|---|
| `nightly_settlement` | `0 2 * * *` | billing `POST /internal/settle` |
| `daily_revenue_rollup` | `30 2 * * *` | Postgres `daily_revenue` |
| `zone_utilisation_daily` | `0 3 * * *` | Postgres `zone_utilisation` |
| `zone_utilisation_hourly` | `5 * * * *` | Postgres `zone_utilisation` |
| `bq_bay_events_export` | `*/15 * * * *` | BigQuery `analytics.bay_snapshots` |
| `bq_reservations_export` | `0 * * * *` | BigQuery `analytics.reservations` |
| `bq_revenue_export` | `45 3 * * *` | BigQuery `analytics.daily_revenue` |
| `bq_tariff_snapshot` | `0 1 * * 1` | BigQuery `analytics.tariff_history` |
| `s3_invoice_export` | `15 4 * * *` | S3 bucket `RECEIPTS_BUCKET` (`exports/invoices/`) |
| `s3_audit_export` | `0 4 * * 1` | S3 bucket `RECEIPTS_BUCKET` (`exports/audit/`) |

1 DAG to billing, 3 to Postgres, 4 to BigQuery, 2 to S3. `_common.py` and
`pg_revenue_correction.py` are helper modules, not DAGs.

Environment on the Airflow workers: `DB_HOST`, `DB_USER`, `DB_PASSWORD`,
`BQ_PROJECT`, `RECEIPTS_BUCKET`, `BILLING_URL=http://billing:8080`.

## Registration

The project is deployed by syncing `dags/` to the Airflow DAG bucket, leaving
the folders of the `features` and `forecast` projects there alone:

```bash
gsutil -m rsync -r -d -x '^(features|forecast|pipelines_shared)/' jobs/dags "gs://${AIRFLOW_DAGS_BUCKET}/dags"   # registers service nightly-jobs
```

`deploy/register.sh` runs this together with the two other Airflow projects'
registrations.
