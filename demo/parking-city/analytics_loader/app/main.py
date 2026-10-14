"""Analytics loader: pulls bay-status messages and loads them into BigQuery.

Unlike the dashboard (push), this service *pulls* from its own subscription
(bay-status-analytics), so it can fall behind or batch without the broker
pushing at it.
"""
import json
import logging
import time

from common_py.pubsub import Puller

from .warehouse import BayEventsTable

log = logging.getLogger("analytics-loader")


def main() -> None:
    puller = Puller("bay-status-analytics")
    table = BayEventsTable()

    while True:
        received = puller.pull(max_messages=200)
        if not received:
            time.sleep(1)
            continue
        rows = [json.loads(m.message.data) for m in received]
        errors = table.insert(rows)
        if errors:
            log.error("bigquery rejected rows: %s", errors)
            continue  # not acked: Pub/Sub redelivers
        puller.ack([m.ack_id for m in received])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
