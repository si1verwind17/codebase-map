# forecast: demand-forecast (Flyte)

Flyte project `forecast`. The workflow in `workflows.py` uses a
`reference_task` to `compute_zone_features` in the `features` project
(service `feature-store`), reads BigQuery, and writes the Postgres table
`demand_forecast`, which `pricing` reads.

Registration (also in `deploy/register.sh`). `pipelines_shared/` is registered
into this project as well as into `features`:

```bash
pyflyte register --project forecast --domain production --image "$PIPELINE_IMAGE" forecast pipelines_shared
```
