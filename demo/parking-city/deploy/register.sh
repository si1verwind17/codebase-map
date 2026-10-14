#!/usr/bin/env bash
# Registers the orchestrated projects. Runtime services are deployed from
# docker-compose.yml; these three are deployed by registration.
set -euo pipefail

# Airflow project -> service "nightly-jobs"
gsutil -m rsync -r -d jobs/dags "gs://${AIRFLOW_DAGS_BUCKET}/dags"

# Flyte project "features" -> service "feature-store"
pyflyte register --project features --domain production --image "${PIPELINE_IMAGE}" features pipelines_shared

# Flyte project "forecast" -> service "demand-forecast"
pyflyte register --project forecast --domain production --image "${PIPELINE_IMAGE}" forecast pipelines_shared
