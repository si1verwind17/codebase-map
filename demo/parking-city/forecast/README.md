# forecast: demand-forecast (Airflow 2)

Airflow project `forecast`. The `demand_forecast` DAG in `demand_forecast.py`
(`30 1 * * *`) triggers `zone_features` in the `features` project (service
`feature-store`) and waits for it, reads BigQuery, and writes the Postgres
table `demand_forecast`, which `pricing` reads.

Registration (also in `deploy/register.sh`). `pipelines_shared/` is synced with
this project as well as with `features`:

```bash
gsutil -m rsync -r -d forecast "gs://${AIRFLOW_DAGS_BUCKET}/dags/forecast"
gsutil -m rsync -r -d pipelines_shared "gs://${AIRFLOW_DAGS_BUCKET}/dags/pipelines_shared"
```
