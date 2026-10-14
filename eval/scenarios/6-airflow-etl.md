# Scenario 6: an Airflow ETL repo (skill arm only)

Does the agent map scheduled data jobs: who runs them, what they read and write, the generic job's tables, a DAG that
triggers another, and the job run by hand?

**Fixture:** `warehouse-jobs`, one temp repo, `git init` + one commit of the files below.

```yaml
# docker-compose.yml
services:
  airflow-scheduler:
    image: apache/airflow:2.10.3
    command: scheduler
    volumes: ["./dags:/opt/airflow/dags", "./common:/opt/airflow/common"]
    environment:
      LEGACY_DB_URL: mysql+pymysql://etl@legacy-mysql/shop
      WAREHOUSE_DSN: postgresql://etl@warehouse/analytics
      REPORT_BUCKET: acme-reports
  legacy-mysql:
    image: mysql:8.4
  warehouse:
    image: postgres:16
```

`README.md`: a heading, one line "The DAGs in `dags/` run on the scheduler in `docker-compose.yml`.", and one line
"Backfill a day by hand: `airflow dags trigger orders_backfill --conf '{"day": "2026-01-01"}'`."
`requirements.txt`: `apache-airflow==2.10.3`, `pandas`, `sqlalchemy`, `pymysql`, `psycopg`, `google-cloud-storage`.
`common/__init__.py`: empty.

```python
# common/replicate.py
import os

import pandas as pd
from sqlalchemy import create_engine


def copy_tables(tables: list[str]) -> int:
    """Copy whole tables from the legacy shop database into the warehouse, same schema and name."""
    source = create_engine(os.environ["LEGACY_DB_URL"])
    target = create_engine(os.environ["WAREHOUSE_DSN"].replace("postgresql://", "postgresql+psycopg://"))
    for table in tables:
        frame = pd.read_sql(f"SELECT * FROM {table}", source)
        schema, name = table.split(".")
        frame.to_sql(name, target, schema=schema, if_exists="replace", index=False)
    return len(tables)
```

```python
# dags/orders_ingest.py
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

from common.replicate import copy_tables


def chunked(rows: list, size: int) -> list:
    out = []
    for i in range(0, len(rows), size):
        out.append(rows[i:i + size])
    return out


def copy_orders() -> int:
    return copy_tables(["shop.orders", "shop.order_items"])


with DAG("orders_ingest", schedule="0 2 * * *", start_date=datetime(2026, 1, 1), catchup=False):
    PythonOperator(task_id="copy_orders", python_callable=copy_orders)
```

```python
# dags/customers_ingest.py
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator

from common.replicate import copy_tables


def chunked(rows: list, size: int) -> list:
    out = []
    for i in range(0, len(rows), size):
        out.append(rows[i:i + size])
    return out


def copy_customers() -> int:
    return copy_tables(["shop.customers"])


with DAG("customers_ingest", schedule="30 2 * * *", start_date=datetime(2026, 1, 1), catchup=False):
    PythonOperator(task_id="copy_customers", python_callable=copy_customers)
```

```python
# dags/revenue_report.py
import os
from datetime import datetime

import psycopg
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from google.cloud import storage


def chunked(rows: list, size: int) -> list:
    out = []
    for i in range(0, len(rows), size):
        out.append(rows[i:i + size])
    return out


def build_revenue() -> str:
    with psycopg.connect(os.environ["WAREHOUSE_DSN"]) as conn:
        rows = conn.execute("SELECT order_day, sum(total) FROM shop.orders GROUP BY order_day").fetchall()
    blob = storage.Client().bucket(os.environ["REPORT_BUCKET"]).blob("revenue.csv")
    blob.upload_from_string("\n".join(f"{day},{total}" for day, total in rows))
    return blob.name


with DAG("revenue_report", schedule="0 4 * * *", start_date=datetime(2026, 1, 1), catchup=False):
    refresh = TriggerDagRunOperator(task_id="refresh_customers", trigger_dag_id="customers_ingest",
                                    wait_for_completion=True)
    report = PythonOperator(task_id="build_revenue", python_callable=build_revenue)
    refresh >> report
```

```python
# dags/orders_backfill.py
import os
from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator
from sqlalchemy import create_engine, text


def backfill(**context) -> int:
    day = context["dag_run"].conf["day"]
    source = create_engine(os.environ["LEGACY_DB_URL"])
    target = create_engine(os.environ["WAREHOUSE_DSN"].replace("postgresql://", "postgresql+psycopg://"))
    with source.connect() as src, target.begin() as dst:
        rows = src.execute(text("SELECT id, order_day, total FROM shop.orders WHERE order_day = :day"), {"day": day})
        for row in rows:
            dst.execute(text("INSERT INTO shop.orders_backfill (id, order_day, total) VALUES (:id, :d, :t)"),
                        {"id": row.id, "d": row.order_day, "t": row.total})
    return 0


with DAG("orders_backfill", schedule=None, start_date=datetime(2026, 1, 1), catchup=False):
    PythonOperator(task_id="backfill", python_callable=backfill)
```

**Prompt:** the shared one in [`eval/README.md`](../README.md), with the repo's path.

**Ground truth** (`from` rolls up to the service; finer method ends count):

| # | From | Kind | Target |
|---|---|---|---|
| 1 | the scheduler service (orders and customers ingest) | db-read | legacy MySQL, `shop.*` |
| 2 | the scheduler service (orders and customers ingest) | db-write | warehouse Postgres, `shop.*` |
| 3 | revenue_report | batch | customers_ingest (`TriggerDagRunOperator`) |
| 4 | revenue_report | db-read | warehouse `shop.orders` |
| 5 | revenue_report | ext-call, or db-write to a `bucket` datastore | Google Cloud Storage (`REPORT_BUCKET`) |
| 6 | the hand-run service (orders_backfill) | db-read | legacy `shop.orders` |
| 7 | the hand-run service (orders_backfill) | db-write | warehouse `shop.orders_backfill` |

**Checks** (PASS/FAIL):

1. **Valid map and page:** `validate.py` exits 0 and `index.html` exists.
2. **Deployables:** the scheduled DAGs belong to a service citing the compose `airflow-scheduler` service (one
   service, or one per DAG group) and their code sits under that service; `orders_backfill` is in a hand-run service
   citing the README line (a twin of the DAG folder, or its own module); `common` is a library; no service for MySQL
   or Postgres (they are datastores).
3. **Recall:** at least 6 of the 7 rows present.
4. **Library calls credited:** rows 1 and 2 start at a service or a DAG method (`copy_orders`, `copy_customers`),
   never inside `common`, and name `copy_tables` in `via`.
5. **Trigger:** row 3 is a `batch` relation keyed `task <name>`, from revenue_report's service or a node inside it,
   ending at customers_ingest's task method.
6. **Generic copy:** rows 1 and 2 have a wildcard key, and their `tables` list `shop.orders`, `shop.order_items` and
   `shop.customers`.
7. **Schedules:** `orders_ingest` `0 2 * * *`, `customers_ingest` `30 2 * * *`, `revenue_report` `0 4 * * *`,
   `orders_backfill` `manual`.
8. **No platform nodes:** no node for Airflow, its scheduler or pandas.
9. **Copy-paste visible:** `problems` holds the scanner's copy-paste entry naming `chunked` (three DAG files define
   it).
10. **Pins and examples:** 3–6 pins (ids the slugs of their titles); `scripts/examples.py <repo>` reports
    `(0 without an example)` for entry points with no `missing some keys`.

A miss is a SKILL.md wording fix, not a test change.
