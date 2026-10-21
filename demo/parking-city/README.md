# parking-city

A fictional city parking network, written as a showcase for the
`visualizing-codebases` skill. It is illustrative code: realistic and
consistent, but it does not need to build, run or pass tests. It exists so the
code-map viewer can be demonstrated and tested on
something public, with every kind of factory element present at least once.

Eleven runtime services (Scala 3 + ZIO 2 + tapir, and Python), two shared
libraries and three Airflow projects.

## How it is wired

- `docker-compose.yml` lists every runtime service with its `build:` folder and
  environment. Base URLs for calls between services come from env vars set
  there (for example `PRICING_URL=http://pricing:8080`).
- Databases, caches, brokers and SaaS are not started by compose. They are
  reached through env keys (`DB_HOST`, `REDIS_URL`, `SHARED_CACHE_URL`,
  `KAFKA_BROKERS`, `BQ_PROJECT`, `RECEIPTS_BUCKET`, `VIOLATIONS_QUEUE_URL`,
  `FINES_API_URL`, `SMTP_HOST`, `SENSORCLOUD_WS_URL`, ...) or fixed vendor hosts.
- One Postgres holds all tables (`sql/schema.sql` shows the owner of each);
  the analytics warehouse is BigQuery.
- The three Airflow projects are deployed by registration into one DAG bucket
  (`deploy/register.sh`, `jobs/README.md`, `forecast/README.md`,
  `features/README.md`).

## Services

| Service | Language | Folder |
|---|---|---|
| `reservations` | Scala | `reservations/` |
| `pricing` | Scala | `pricing/` |
| `billing` | Scala | `billing/` |
| `notifier` (2 replicas) | Python | `notifier/` |
| `sensor-gateway` | Python | `sensor_gateway/` |
| `occupancy` | Python | `occupancy/` |
| `enforcement-worker` (3 replicas) | Python | `enforcement_worker/` |
| `payments-webhook` | Python | `payments_webhook/` |
| `city-dashboard` | Python | `city_dashboard/` |
| `analytics-loader` | Python | `analytics_loader/` |
| `reporting-api` | Python | `reporting_api/` |
| `nightly-jobs` (Airflow) | Python | `jobs/` |
| `demand-forecast` (Airflow) | Python | `forecast/` |
| `feature-store` (Airflow) | Python | `features/` |

Libraries: `common` (Scala: JDBC helper, Kafka producer, config; used by
reservations, pricing, billing) and `common_py` (Python: Pub/Sub wrapper,
Redis cache helper, Twilio SMS client, SMTP mailer, DB connect).

## Which factory element each part demonstrates

| Factory element | Where it comes from |
|---|---|
| Belt (request/response between services) | `reservations/.../PricingClient.scala` calls `GET /v1/quote` served by `pricing/.../QuoteEndpoint.scala`; `jobs/dags/nightly_settlement.py` calls `POST /internal/settle` served by `billing/.../SettleEndpoint.scala` |
| Pipe (stream) | `sensor_gateway/app/vendor.py` (WebSocket in from the vendor) and `sensor_gateway/app/uplink.py` -> `occupancy/app/grpc_server.py` (gRPC bidirectional `OccupancyFeed/Stream`, `proto/occupancy.proto`) |
| Drone / fan-out (event topic) | Kafka `reservation-events`: produced by `reservations/.../OutboxRelay.scala`, consumed by `billing` (group `billing`) and `notifier` (group `notifier`) |
| Work queue | SQS `violations`: sent by `occupancy/app/overstay.py`, consumed by `enforcement_worker/app/main.py` (`deploy/sqs.yaml`) |
| Push subscription | `city_dashboard/app/main.py` `POST /pubsub/bay-status`; `deploy/pubsub.yaml` subscription `bay-status-dashboard` with `push_endpoint` |
| Pull subscription | `analytics_loader/app/main.py` + `common_py/common_py/pubsub.py` `Puller.pull`; subscription `bay-status-analytics` |
| Dead letters | `billing/.../DeadLetters.scala` produces to `reservation-events.dlq` when event handling fails (`ReservationEventsConsumer.scala`) |
| Rail yard (busy batch destinations) | `jobs/dags/*.py`: 10 DAGs, 4 to BigQuery, 3 to Postgres, 2 to S3, 1 to billing; several run many times a day (`*/15`, hourly) |
| Cross-project batch | `forecast/demand_forecast.py` `TriggerDagRunOperator` to the `zone_features` DAG in `features/zone_features.py` |
| Warehouse + lane (database) | Postgres tables `reservations`, `reservation_outbox`, `tariffs`, `zones`, `invoices`, `payments`, `bay_status`, `daily_revenue`, `zone_utilisation`, `demand_forecast` (`sql/schema.sql`); BigQuery `analytics.bay_events` and friends |
| Own cache | `reservations/.../QuoteCache.scala` on `REDIS_URL`, read by nobody else |
| Shared cache | `SHARED_CACHE_URL`: written by `occupancy` (`common_py/common_py/cache.py`), read by `pricing/.../SharedCache.scala` and `city_dashboard/app/main.py` |
| Bucket | S3 `RECEIPTS_BUCKET`: `billing/.../ReceiptStore.scala` (receipts), `jobs/dags/s3_*.py` (exports) |
| Outside docks (yellow) | Stripe (`reservations/.../StripeGateway.scala`, `billing/.../StripeCharger.scala`), Google Maps (`pricing/.../Geocoder.scala`), Twilio (`common_py/common_py/sms.py`), SMTP (`common_py/common_py/mailer.py`), sensor vendor WebSocket (`vendor.py`), city fines API (`enforcement_worker/app/fines.py`), accounts API (`notifier/app/directory.py`) |
| Inbound webhook | `payments_webhook/app/main.py` `POST /webhooks/stripe` |
| Read-only service | `reporting_api/app/main.py`: only SELECTs on `reservations`, `invoices`, `bay_status` |
| Libraries (parts racks) | `common/` (sbt module) and `common_py/` (package) |
| Twin | `pipelines_shared/` synced by both the `features` and the `forecast` registration, `deploy/register.sh` |
| Replicas | `deploy.replicas` in `docker-compose.yml`: `notifier` 2, `enforcement-worker` 3 |
| Deliberate smell | see below |

## Deliberate smell

`payments_webhook/app/store.py` `mark_reservation` runs
`UPDATE reservations SET status = ...`, a table owned by the `reservations`
service (`reservations/.../ReservationRepo.scala` writes the same column). The
map should make this cross-service write visible: a second service has a write
lane into the `reservations` warehouse. The proper design would have
`payments-webhook` publish an event, or call a reservations endpoint.

A milder thing the map will also show: `occupancy` reads `reservations` (to
detect overstays) and the Airflow DAGs read several tables owned by services.
Those are reads, not ownership violations.
