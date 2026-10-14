# features: feature-store (Flyte)

Flyte project `features`. `workflows.py` holds the `compute_zone_features`
task, which the `forecast` project calls through a `reference_task`.

Registration (also in `deploy/register.sh`). `pipelines_shared/` is registered
into this project as well as into `forecast`:

```bash
pyflyte register --project features --domain production --image "$PIPELINE_IMAGE" features pipelines_shared
```
