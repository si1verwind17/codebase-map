# Scenario 7: an in-process queue (skill arm only)

Does the agent join a producer and a background consumer that share an in-process queue, and leave a queue one
method fills and drains alone?

**Fixture:** `kitchen`, one temp repo, `git init` + one commit of the files below.

```text
docker-compose.yml   services: orders (build ./orders; env DATABASE_URL, KAFKA_BOOTSTRAP)
orders/Dockerfile    FROM python:3.12-slim / COPY . /app / WORKDIR /app / RUN pip install -r requirements.txt /
                     CMD ["uvicorn", "orders.main:app"]
orders/requirements.txt  fastapi, pydantic, aiokafka, asyncpg, httpx
orders/orders/__init__.py   empty
```

```python
# orders/orders/models.py
from pydantic import BaseModel


class OrderIn(BaseModel):
    table: int
    dishes: list[str]


class Ticket(BaseModel):
    ticket_id: str
    table: int
    dishes: list[str]
```

```python
# orders/orders/kitchen.py
import json
import os

import asyncpg
from aiokafka import AIOKafkaProducer

from .models import Ticket


async def cook(ticket: Ticket, producer: AIOKafkaProducer) -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        await conn.execute("INSERT INTO tickets (ticket_id, table_no, dishes) VALUES ($1, $2, $3)",
                           ticket.ticket_id, ticket.table, ticket.dishes)
    finally:
        await conn.close()
    await producer.send_and_wait("ticket-ready", json.dumps(ticket.model_dump()).encode())


async def run(tickets, producer: AIOKafkaProducer) -> None:
    while True:
        ticket = await tickets.get()
        await cook(ticket, producer)
        tickets.task_done()
```

```python
# orders/orders/stock.py
import asyncio

import httpx


async def check_all(urls: list[str], workers: int = 4) -> list[int]:
    jobs: asyncio.Queue = asyncio.Queue()
    for url in urls:
        jobs.put_nowait(url)
    codes: list[int] = []

    async def fetch(client: httpx.AsyncClient) -> None:
        while not jobs.empty():
            url = jobs.get_nowait()
            codes.append((await client.get(url)).status_code)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*(fetch(client) for _ in range(workers)))
    return codes
```

```python
# orders/orders/main.py
import asyncio
import os
import uuid

from aiokafka import AIOKafkaProducer
from fastapi import FastAPI

from . import kitchen
from .models import OrderIn, Ticket

app = FastAPI()
tickets: asyncio.Queue = asyncio.Queue(maxsize=500)
producer = AIOKafkaProducer(bootstrap_servers=os.environ["KAFKA_BOOTSTRAP"])


@app.on_event("startup")
async def start() -> None:
    await producer.start()
    asyncio.create_task(kitchen.run(tickets, producer))


@app.post("/v1/orders")
async def place(order: OrderIn) -> Ticket:
    ticket = Ticket(ticket_id=str(uuid.uuid4()), table=order.table, dishes=order.dishes)
    await tickets.put(ticket)
    return ticket
```

**Prompt:** the shared one in [`eval/README.md`](../README.md), with the repo's path.

**Checks** (PASS/FAIL):

1. **Valid:** `scripts/validate.py docs/viz-code/code-map.json` exits 0.
2. **Queue:** exactly one `in-process-queue` node: parent the orders service, `delivery: queue`, `evidence` citing
   `orders/orders/main.py` line 12 (`tickets` is created there). No `topic` node stands for it.
3. **Hand-offs:** a `hand-off` from `place` to the queue and one from the queue to `kitchen.run` (or `kitchen.cook`,
   the method that handles each ticket); `confidence` `confirmed`, or `inferred` with a `why`.
4. **Trace:** following `calls` and runtime relations (`hand-off` included) downstream from `place` reaches both the
   `ticket-ready` topic and the `tickets` table.
5. **Not a hand-off:** no `in-process-queue` node for `stock.py`'s `jobs` queue (one method fills and drains it), and
   `audit.md` lists no `queue.missing` warning (a `problems` entry names `orders/orders/stock.py:7`).
6. **Reported:** the reply's counts line agrees with the map.
