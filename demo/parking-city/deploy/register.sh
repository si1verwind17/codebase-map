#!/usr/bin/env bash
# Registers the orchestrated projects. Runtime services are deployed from
# docker-compose.yml; these three are deployed by registration.
# All three share one Airflow DAG bucket, each project in its own folder.
set -euo pipefail

# Airflow project -> service "nightly-jobs"
gsutil -m rsync -r -d -x '^(features|forecast|pipelines_shared)/' jobs/dags "gs://${AIRFLOW_DAGS_BUCKET}/dags"

# Airflow project "features" -> service "feature-store"
gsutil -m rsync -r -d features "gs://${AIRFLOW_DAGS_BUCKET}/dags/features" && gsutil -m rsync -r -d pipelines_shared "gs://${AIRFLOW_DAGS_BUCKET}/dags/pipelines_shared"

# Airflow project "forecast" -> service "demand-forecast"
gsutil -m rsync -r -d forecast "gs://${AIRFLOW_DAGS_BUCKET}/dags/forecast" && gsutil -m rsync -r -d pipelines_shared "gs://${AIRFLOW_DAGS_BUCKET}/dags/pipelines_shared"
