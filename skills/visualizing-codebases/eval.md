# Benchmark: visualizing-codebases

The scenarios here run the skill arm only (skill loaded), one rep each (a
run costs ~150k tokens), Sonnet, graded by an independent judge against the
checks below. A control arm (skill NOT loaded; its prompt must explicitly
forbid loading any skill, per the writing-skills protocol) is optional; when
one runs, it runs as below.

**Control arm gets the output contract**, not the method: a copy of
`format.md` and `scripts/schema/code-map.schema.json` in `<workdir>/contract/`,
and no scripts. Every run's output is checked with the skill's
`scripts/validate.py` (the judge runs it).

**Prompt** (verbatim, with the fixture's path; skill arm prepends "Before
starting, read `<skill path>/SKILL.md` and follow it as authoritative for how
you work."; control arm prepends "Do not load or read any skill, SKILL.md, or
convention guide from the environment." and appends "The output format is
specified in <workdir>/contract/."):

> Map the repository at `<repo path>` for a code-map viewer: its
> services, how they interact, what they read and write, where to start
> reading, and example data for what comes in. Write the result to
> `docs/viz-code/code-map.json` in that repo. Do not commit. When done,
> reply with ONLY the path you wrote and one line of counts.

Scenarios on the maintainer's private repositories (a blind map, an
incremental rescan, the comment loop) are kept locally by
the maintainer, with their run log.

## Scenario 1: unknown stack (skill arm only)

Can the agent work out a stack the packs do not know, from the code alone?

**Fixture:** two temp repos built from `scripts/tests/conftest.py`: `FLASK`
(as `shopfront`) and `HTTP4S` (as `users-service`), each `git init` + one
commit, **without** a `stack.yaml` (a one-off script under the scratch
directory imports the constants and writes them, as the `make_repo` fixture
does). Do not give the agent `FLASK_STACK` or `HTTP4S_STACK`.

**Prompt:** the one above, once per repo, with the repo's path.

**Checks** (PASS/FAIL per repo):

1. **Stack resolved:** after the run, `summary.md` reads
   `## Stack — nothing unrecognised`.
2. **Routes found:** every route of the fixture test is in `structure.json`
   (method, path, handler): Flask, the 6 of `test_flask_routes_with_stack`
   (`GET`/`DELETE /users/{id}`, `POST /users`, `GET /users`, `GET /health`,
   `GET /ping`; its handler may be the file, or the view a `view_func` names);
   http4s, the 2 of `test_http4s_with_stack` (`GET /users/{id}`, `POST /users`).
3. **Honest groups:** no pattern matches a non-route line; Celery is in
   `imports` (`event`), `marshmallow` / `io.circe` in `ignore`, never the
   reverse.
4. **Reported:** `stack.yaml` holds the entries the run added and the transcript's last summary names any Stack
   line left unresolved (the prompt limits the reply to a path and counts, so grade this from the files).

A miss is a SKILL.md wording fix, not a test change.

## Scenario 2: unknown framework in a new language (skill arm only)

Can the agent describe a framework no pack knows, in a language other than
Python and Scala, with SKILL.md alone? Go Fiber and Hono are in no pack;
pgx and ioredis are.

**Fixture:** two temp repos, each `git init` + one commit of the files below,
**without** a `stack.yaml`.

`catalog` (Go):

```text
go.mod      module example.com/catalog
            go 1.22
            require (github.com/gofiber/fiber/v2 v2.52.5; github.com/jackc/pgx/v5 v5.6.0)
Dockerfile  FROM golang:1.22 / COPY . /src / RUN cd /src && go build -o /app . / CMD ["/app"]
```

```go
// main.go
package main

import (
	"context"
	"os"

	"github.com/gofiber/fiber/v2"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct{ db *pgxpool.Pool }

func (h *Handler) GetItem(c *fiber.Ctx) error {
	var name string
	row := h.db.QueryRow(context.Background(), "SELECT name FROM items WHERE id = $1", c.Params("id"))
	if err := row.Scan(&name); err != nil {
		return fiber.ErrNotFound
	}
	return c.JSON(fiber.Map{"name": name})
}

func (h *Handler) CreateItem(c *fiber.Ctx) error {
	_, err := h.db.Exec(context.Background(), "INSERT INTO items (name) VALUES ($1)", c.FormValue("name"))
	return err
}

func Health(c *fiber.Ctx) error { return c.SendString("ok") }

func main() {
	pool, _ := pgxpool.New(context.Background(), os.Getenv("DATABASE_URL"))
	h := &Handler{db: pool}
	app := fiber.New()
	api := app.Group("/api")
	api.Get("/items/:id", h.GetItem)
	api.Post("/items", h.CreateItem)
	app.Get("/health", Health)
	app.Listen(":8080")
}
```

`notes` (TypeScript; `package.json` with `"name": "notes"` and the
dependencies `hono` 4.6.3, `@hono/node-server` 1.13.1, `ioredis` 5.4.1; a
`Dockerfile` running `node dist/index.js`):

```ts
// src/index.ts
import { Hono, type Context } from "hono";
import { serve } from "@hono/node-server";
import Redis from "ioredis";

const redis = new Redis(process.env.REDIS_URL ?? "redis://localhost:6379");
const app = new Hono();
const notes = new Hono();

async function getNote(c: Context) {
  const body = await redis.get(`note:${c.req.param("id")}`);
  return body ? c.json(JSON.parse(body)) : c.notFound();
}

async function putNote(c: Context) {
  await redis.set(`note:${c.req.param("id")}`, JSON.stringify(await c.req.json()));
  return c.body(null, 204);
}

notes.get("/:id", getNote);
notes.put("/:id", putNote);
app.route("/notes", notes);
app.get("/health", (c) => c.text("ok"));

serve({ fetch: app.fetch, port: 3000 });
```

**Prompt:** the one above, once per repo, with the repo's path.

**Checks** (PASS/FAIL per repo):

1. **Stack resolved:** after the run, `summary.md` reads
   `## Stack — nothing unrecognised`.
2. **Routes found:** `structure.json` holds every route with its handler:
   catalog `GET /items/{id}` (`Handler#GetItem`), `POST /items`
   (`Handler#CreateItem`), `GET /health` (`Health`); notes `GET /{id}`
   (`getNote`), `PUT /{id}` (`putNote`), `GET /health` (the file: an inline
   handler). A sample `stack.yaml` gives exactly these (checked 2026-10-13).
3. **Mounts, not routes:** `summary.md` lists catalog's `/api` and notes'
   `/notes → notes` as mounts, and the map composes them: any relation or
   `problems` entry that names these routes writes `/api/items/{id}` and
   `/notes/{id}`.
4. **Sinks attached:** catalog's `items` reads and writes hang on `GetItem` and
   `CreateItem` (pgx, a pack library); notes' Redis read and write on `getNote`
   and `putNote` (ioredis).
5. **Honest groups:** no pattern matches a non-route line (`redis.get(` with a
   template string is not a route; every route path starts with `/`); `hono`
   and `github.com/gofiber/fiber` are in `imports` as `http-in`;
   `@hono/node-server` is in `ignore` or `imports`, never a route.
6. **Reported:** as Scenario 1's check 4, from `stack.yaml` and the transcript (the reply is only a path and counts).

A miss is a SKILL.md wording fix, not a test change.

## Scenario 3: pins and examples on a first scan (skill arm only)

Does the agent write pinned traces and examples unaided, from SKILL.md alone?

**Fixture:** `lending`, one temp repo, `git init` + one commit of the files below.

```text
docker-compose.yml   services: loans (build ./loans; env KAFKA_BOOTSTRAP, DATABASE_URL),
                     notices (build ./notices; env KAFKA_BOOTSTRAP)
loans/Dockerfile     FROM python:3.12-slim / COPY . /app / WORKDIR /app / RUN pip install -r requirements.txt /
                     CMD ["uvicorn", "loans.main:app"]
loans/requirements.txt  fastapi, pydantic, kafka-python, psycopg
notices/Dockerfile   FROM python:3.12-slim / COPY . /app / WORKDIR /app / RUN pip install kafka-python /
                     CMD ["python", "-m", "notices.main"]
loans/loans/__init__.py, notices/notices/__init__.py   empty
```

```python
# loans/loans/models.py
from pydantic import BaseModel


class LoanRequest(BaseModel):
    member_id: str
    book_isbn: str
    days: int


class Loan(BaseModel):
    loan_id: str
    member_id: str
    book_isbn: str
    due_date: str
```

```python
# loans/loans/events.py
from dataclasses import dataclass


@dataclass
class LoanOpened:
    loan_id: str
    member_id: str
    due_date: str
```

```python
# loans/loans/main.py
import json
import os
import uuid
from datetime import date, timedelta

import psycopg
from fastapi import FastAPI
from kafka import KafkaProducer

from .events import LoanOpened
from .models import Loan, LoanRequest

app = FastAPI()
producer = KafkaProducer(bootstrap_servers=os.environ["KAFKA_BOOTSTRAP"])


def save(loan: Loan) -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        conn.execute("INSERT INTO loans (loan_id, member_id, book_isbn, due_date) VALUES (%s, %s, %s, %s)",
                     (loan.loan_id, loan.member_id, loan.book_isbn, loan.due_date))


def announce(event: LoanOpened) -> None:
    producer.send("loan-events", json.dumps(event.__dict__).encode())


@app.post("/v1/loans")
def open_loan(req: LoanRequest) -> Loan:
    due = (date.today() + timedelta(days=req.days)).isoformat()
    loan = Loan(loan_id=str(uuid.uuid4()), member_id=req.member_id, book_isbn=req.book_isbn, due_date=due)
    save(loan)
    announce(LoanOpened(loan_id=loan.loan_id, member_id=loan.member_id, due_date=due))
    return loan


@app.get("/v1/loans/{loan_id}")
def get_loan(loan_id: str) -> Loan:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        row = conn.execute("SELECT loan_id, member_id, book_isbn, due_date FROM loans WHERE loan_id = %s",
                           (loan_id,)).fetchone()
    return Loan(loan_id=row[0], member_id=row[1], book_isbn=row[2], due_date=row[3])
```

```python
# notices/notices/main.py
import json
import os
from dataclasses import dataclass

from kafka import KafkaConsumer


@dataclass
class LoanOpened:
    loan_id: str
    member_id: str
    due_date: str


def send_reminder(event: LoanOpened) -> str:
    return f"Member {event.member_id}: loan {event.loan_id} is due {event.due_date}"


def handle(message: bytes) -> None:
    event = LoanOpened(**json.loads(message))
    print(send_reminder(event))


def main() -> None:
    consumer = KafkaConsumer("loan-events", bootstrap_servers=os.environ["KAFKA_BOOTSTRAP"], group_id="notices")
    for msg in consumer:
        handle(msg.value)


if __name__ == "__main__":
    main()
```

**Prompt:** the one above, with the repo's path.

**Checks** (PASS/FAIL):

1. **Valid:** `scripts/validate.py docs/viz-code/code-map.json` exits 0.
2. **Pins:** 3–6 pins, each `by: agent`, `id` the slug of its title, `start` a node in the map, `direction` one of
   the three; no title matches `/\b(key|main|critical|core|important)\b/i`.
3. **Entry points:** `scripts/examples.py <repo>` reports `Entry points: N (0 without an example)`; `open_loan`'s
   request holds `member_id`, `book_isbn`, `days` and its response a loan; the consumer's entry (the method the
   `event` from the topic ends at) has a `request` and no `response`.
4. **Data types:** the same report reads `Data types: N (0 without an example)` and lists at least `LoanRequest`
   and `Loan`; every example carries a `fingerprint` in the map, and `meaning.json` holds none (the agent left them
   to `assemble.py`).
5. **Reported:** the reply's counts line agrees with the map.

## Scenario 4: a rescan with a changed type and pins from the viewer (skill arm only)

Does the agent rewrite stale examples and apply a `## Pins` export?

**Setup** (by the judge, on Scenario 3's repo after its run):

1. Commit the map as the agent left it (`git add -A && git commit -m map`; the working files stay ignored).
2. In the committed `docs/viz-code/code-map.json`, append a user pin to `pins`:
   `{"id": "overdue-check", "title": "overdue check", "start": "<the notices consumer's method id>", "direction": "upstream", "by": "user"}`;
   commit ("a user pin").
3. In `loans/loans/models.py` make `Loan.due_date` a `date` (`from datetime import date`; `due_date: date`) and add
   a field `renewals: int = 0` to `Loan`; commit ("due date is a date").
4. Write `docs/viz-code/export-comment.md` (not committed):

```
## Pins
- pin: member looks up a loan | start: <get_loan's method id> | direction: downstream
- unpin: <the id of the agent's first pin>
- unpin: overdue-check
```

**Prompt:** "Before starting, read `<skill path>/SKILL.md` and follow it as authoritative for how you work. Refresh
the code map of the repository at `<repo path>` (output `docs/viz-code`) for the latest commit. Do not commit."

**Checks** (PASS/FAIL):

1. **Stale found:** `stale.json` has mode `incremental` and `stale_examples` naming `Loan` and the entries of
   `open_loan` and `get_loan`.
2. **Rewritten:** `assemble.py` exited 0 (the map's commit is HEAD); `Loan`'s example value has a `renewals` number
   (the fingerprint alone would change on a flag clear); nothing in the map is `stale`.
3. **Pins applied:** a `by: user` pin `member-looks-up-a-loan` with that start and `downstream`, and no second pin
   with that start and direction (an agent pin there became the user's); the unpinned agent
   pin is gone from `pins` and listed in `unpinned`; `overdue-check` is gone and not in `unpinned`.
4. **Export handled:** `docs/viz-code/export-comment.md` is deleted.
5. **Reported:** the reply names each `## Pins` line as applied and the stale examples rewritten.

A miss is a SKILL.md wording fix, not a test change.

## Scenario 5: packs that know the stack (skill arm only)

Do the built-in packs carry a Rails, a Laravel and a Spring service with no `stack.yaml` work, and does the agent
give a method serving several routes an example per key?

**Fixture:** three temp repos, each `git init` + one commit of the files below, **without** a `stack.yaml`.

`library` (Ruby): `Gemfile` with `source "https://rubygems.org"` and `gem "rails", "~> 7.1"`;
`config/application.rb` with `require "rails/all"` and `module Library; class Application < Rails::Application; end; end`;
`app/controllers/application_controller.rb` with `class ApplicationController < ActionController::API; end`;
`app/models/application_record.rb` with `class ApplicationRecord < ActiveRecord::Base; self.abstract_class = true; end`.

```ruby
# config/routes.rb
Rails.application.routes.draw do
  resources :books, only: [:index, :show, :create]
  resources :members, param: :member_no, except: [:new, :edit, :destroy]
  resource :session, only: %i[create destroy]
  get "/health", to: "health#show"
end
```

```ruby
# app/models/book.rb
class Book < ApplicationRecord
  self.table_name = "catalog_books"
end
```

```ruby
# app/controllers/books_controller.rb
class BooksController < ApplicationController
  def index
    render json: Book.all
  end

  def show
    render json: Book.find(params[:id])
  end

  def create
    render json: Book.create!(params.permit(:title, :isbn)), status: :created
  end
end
```

`app/controllers/members_controller.rb` (`index`, `show`, `create`, `update`, each `render json: {}`),
`app/controllers/sessions_controller.rb` (`create`, `destroy`, each `head :ok`) and
`app/controllers/health_controller.rb` (`show`, `render plain: "ok"`).

`shop` (PHP): `composer.json` `{"name": "demo/shop", "require": {"laravel/framework": "^11.0"}, "autoload":
{"psr-4": {"App\\": "app/"}}}`.

```php
<?php
// routes/api.php: no `use` of the Route facade (the global alias)

use App\Http\Controllers\ProductController;

Route::get('/products', [ProductController::class, 'index']);
Route::match(['put', 'patch'], '/products/{id}', [ProductController::class, 'update']);
Route::middleware('auth:sanctum')->prefix('admin')->group(function () {
    Route::delete('/products/{id}', [ProductController::class, 'destroy']);
});
```

```php
<?php
// app/Http/Controllers/ProductController.php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

class ProductController
{
    public function index()
    {
        return DB::table('products')->get();
    }

    public function update(Request $request, string $id)
    {
        DB::table('products')->where('id', $id)->update($request->only(['name', 'price']));
        return DB::table('products')->find($id);
    }

    public function destroy(string $id)
    {
        DB::table('products')->where('id', $id)->delete();
        return response()->noContent();
    }
}
```

`orders` (Java): `pom.xml` with artifactId `orders` and the dependencies `spring-boot-starter-web`,
`spring-boot-starter-jdbc` and `spring-cloud-starter-openfeign`; a `Dockerfile` running the jar.

```java
// src/main/java/demo/orders/OrderController.java
package demo.orders;

import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/orders")
public class OrderController {
    private final JdbcTemplate jdbc;
    private final PaymentsClient payments;

    public OrderController(JdbcTemplate jdbc, PaymentsClient payments) {
        this.jdbc = jdbc;
        this.payments = payments;
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable String id) {
        return jdbc.queryForMap("SELECT id, total FROM orders WHERE id = ?", id);
    }

    @PostMapping
    public Map<String, Object> place(@RequestBody Map<String, Object> order) {
        jdbc.update("INSERT INTO orders (id, total) VALUES (?, ?)", order.get("id"), order.get("total"));
        return payments.charge(Map.of("order_id", order.get("id"), "amount", order.get("total")));
    }
}
```

```java
// src/main/java/demo/orders/PaymentsClient.java
package demo.orders;

import java.util.Map;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "payments", url = "${payments.url}")
public interface PaymentsClient {
    @PostMapping("/payments")
    Map<String, Object> charge(@RequestBody Map<String, Object> request);
}
```

**Prompt:** the one above, once per repo, with the repo's path.

**Checks** (PASS/FAIL per repo):

1. **Valid, stack known:** `validate.py` exits 0 and `summary.md` reads `## Stack — nothing unrecognised` with no
   `stack.yaml` written (the packs know these stacks).
2. **Routes found:** `structure.json` holds exactly these routes. library: `GET /books`, `GET /books/{id}`,
   `POST /books`, `GET /members`, `POST /members`, `GET /members/{member_no}`, `PATCH` and `PUT
   /members/{member_no}`, `POST /session`, `DELETE /session` and `GET /health` (11; the handler is the routes file).
   shop: `GET /products` (`index`), `PUT` and `PATCH /products/{id}` (`update`), `DELETE /products/{id}`
   (`destroy`), with `/admin` listed as a mount. orders: `GET /orders/{id}` (`get`), `POST /orders` (`place`), and no
   `/payments` route (the Feign interface is a client).
3. **Data attached:** library's `catalog_books` is defined on `Book`; shop's `products` reads and writes hang on
   the three controller methods; orders' `orders` read and write on `get` and `place`, and `place` has an outgoing
   HTTP relation (or a `problems` entry) for the payments service.
4. **An example per key:** `scripts/examples.py <repo>` reports `(0 without an example)` with no `missing some keys`
   for shop and orders; shop's `update` has two entries, `PUT` and `PATCH`. Where the agent wrote the admin route's
   key with its mount, it reads `DELETE /admin/products/{id}`.
5. **Reported:** the reply's counts line agrees with the map.

A miss is a SKILL.md wording fix, not a test change.

## Scenario 6: an Airflow ETL repo (skill arm only)

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

**Prompt:** the one above, with the repo's path.

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

## Editing this skill

A meaning-rule change that can alter facts on existing maps → add a CHANGES.md section and bump RULES_VERSION (see CHANGES.md).

## Pending validation

- Scanner languages, plan 1: the `tables` group, the `ext:` naming rule, build-file modules and `#<lang>` module claims in SKILL.md. Scenario 2 exercises the build-file modules; the rest has no scenario yet.
- Scanner languages, plan 2 (SKILL.md § Stack): the `handler` group, `mount` entries and the language packs passed Scenario 2 once (2026-10-13); the `annotated` form and `skip_class` are in Scenario 5; pack entries replaced by name have no scenario yet.
- Eval fixes (2026-10-14): a `pin:` line matching an agent pin's start and direction converts it (Scenario 4
  check 3); `ext.missing` cleared by a `problems` entry; example keys under a mount — no scenario run yet.
- Minor gaps (2026-10-14): the `expand` key (Rails `resources`), Laravel routes without a `use`, and an example per entry-point key are in Scenario 5.

## Run log

`Skill@` = short git hash of the commit whose SKILL.md content was tested.
"-" for control arms.

| Date | Skill@ | Scenario | Model | Arm | Reps | Score (checks passed / total across reps) | Notes |
|------|--------|----------|-------|-----|------|-------------------------------------------|-------|
| 2026-10-12 | 9f093e6 | 1 | sonnet | skill | 1 | PASS | shopfront 6/6 routes, users-http4s 2/2; both Stack sections `nothing unrecognised` after one extract re-run each. The http4s handler resolved to the class `UserRoutes`: the agent did not add `HttpRoutes` to `effects` (SKILL.md § Stack now says to). |
| 2026-10-13 | 0000bf6 | 2 | sonnet | skill | 1 | PASS | orders-fiber 3/3 routes + `/v1` mount + pgx; catalog-hono 3/3 routes + `/products` mount + ioredis/axios; Stack empty after 3 re-runs. The mount entry needed `path:` (now defaulted to `literal`); inline handlers showed the package id (now the file node). |
| 2026-10-13 | 5bd5cb5 | 3 | sonnet | skill | 4 runs | PASS (run 4; runs 1–3 FAIL check 2) | lending: 3 entry points, all with examples; LoanRequest, Loan and both LoanOpened types; fingerprints left to assemble. Run 1 pinned 2 (SKILL.md now: every service with an entry point gets a pin); run 2 had an id that was not its title's slug (now refused); run 3 pinned 2 again (now the `pin.few` warning). |
| 2026-10-13 | 5bd5cb5 | 4 | sonnet | skill | 1 | PASS | incremental; `stale_examples` named Loan and both route entries; values kept (an ISO date string still fits `date`), Loan fingerprint restamped; user pin got `-2` (the agent had pinned the same title); agent pin moved to `unpinned`; user pin `overdue-check` deleted; export deleted. |
| 2026-10-14 | f2fb33f | 1 | sonnet | skill | 1 | PASS (checks 1–3 both repos; check 4 eval conflict) | shopfront 6/6 routes (`/ping` handler named via `view_func`, sharper than the test's file fallback), users-http4s 2/2 with `HttpRoutes` in `effects`. Check 4 conflicts with the prompt's "reply with ONLY…". The judge found the scenario contaminated: SKILL.md § Stack's worked `stack.yaml` uses Flask/Celery/http4s, the fixture's stacks. |
| 2026-10-14 | f2fb33f | 2 | sonnet | skill | 1 | PASS (checks 1–5 both repos; check 6 eval conflict) | catalog 3/3 routes + `/api` mount, notes 3/3 + `/notes → notes`; Stack empty after 3–5 extract runs. Example keys skip the mount when no relation names the route (SKILL.md mount vs Examples wording disagree). |
| 2026-10-14 | f2fb33f | 3 | sonnet | skill | 1 | 5/5 | 3 pins, 3 entries, 4 types, fingerprints left to assemble; audit clean. |
| 2026-10-14 | f2fb33f | 4 | sonnet | skill | 1 | 5/5 | incremental; Loan + both entries stale, values kept (still valid), restamped; user pin `-2` beside the agent's identical pin (judge: SKILL.md could convert the agent pin instead); check 2 cannot tell a rewrite from a flag clear. |
| 2026-10-14 | f2fb33f | 5 | sonnet | skill | 1 | 14/15 (library 5/5, shop 5/5, orders 4/5) | library 11/11 Rails routes, each mapped to its controller action; shop PUT+PATCH examples on `update`; orders Feign gives no route. orders check 5: reply said 4 relations (5). Scanner: name-only `calls` when the receiver's type is known (`order.get` on a `Map`, `Book.create!`); Rails entry points invisible to `examples.py` (file handler). `text.over-line` on tiny site floors in 5/10 runs. |
| 2026-10-14 | 0333850 | 1 | sonnet | skill | 1 | 8/8 | rerun after the fix round; SKILL.md's worked stack.yaml no longer shows Flask/http4s, and neither agent copied anything fixture-specific; the http4s agent added `HttpRoutes` to `effects` after seeing `routes` was not a method. |
| 2026-10-14 | 0333850 | 3 | sonnet | skill | 1 | 5/5 | 3 pins (the `pin.few` warning raised the first run's 1); 3 entries, 4 types. |
| 2026-10-14 | 0333850 | 4 | sonnet | skill | 1 | 5/5 | `renewals` written into Loan and both entries; the user `pin:` matching the agent's pin converted it (no `-2`); the agent also reported main.py building Loan without `renewals` (setup flaw, now `= 0`). |
| 2026-10-14 | 0333850 | 5 | sonnet | skill | 1 | 15/15 | no name-only `calls` left (`order.get`, `Book.create!`); counts still retold (step 7 now says paste the line); `name.container` on a Java constructor (now skipped). |
| 2026-10-14 | c05954f | 6 | sonnet | skill | 2 runs | run 1 10/10 (looser checks); run 2 8/10 → 10/10 after 80c1e4e | run 2 pasted the counts line verbatim. Checks 2 and 5 failed: `assemble.py` gave the shared `dags` module to `svc:adhoc` (lowest id) though SKILL.md said list the scheduler first; fixed so a deploy-file service owns it over a docs-launched one, re-assembling run 2's own meaning.json passes 2, 5 and 9. |
