# features: feature-store (Airflow 2)

Airflow project `features`. `zone_features.py` holds the `zone_features` DAG
(`0 1 * * *`): its task `compute_zone_features` reads BigQuery
`analytics.bay_events` and writes `analytics.zone_features`. The `forecast`
project also triggers this DAG before each forecast (`TriggerDagRunOperator`).

Registration (also in `deploy/register.sh`). `pipelines_shared/` is synced with
this project as well as with `forecast`:

```bash
gsutil -m rsync -r -d features "gs://${AIRFLOW_DAGS_BUCKET}/dags/features"
gsutil -m rsync -r -d pipelines_shared "gs://${AIRFLOW_DAGS_BUCKET}/dags/pipelines_shared"
```
