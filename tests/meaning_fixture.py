"""A meaning.json an agent could write for the SHOP fixture repo."""

CALL = "r:request:svc:worker->shop::io.demo.shop.api.OrderApi$#getEndpoint/0:GET /v1/orders/{id}"
POST = "r:request:svc:worker->shop::io.demo.shop.api.OrderApi$#createEndpoint/0:POST /v1/orders/create"
WRITE = "r:db-write:shop::io.demo.shop.repo.PgOrderRepo#save/2->db:postgres:DB_HOST/public.orders:table public.orders"
RUN = "worker::worker.main#run/2"
HEALTH = "worker::worker.main#health/0"
CREATE = "shop::io.demo.shop.api.OrderApi$#createEndpoint/0"
GET = "shop::io.demo.shop.api.OrderApi$#getEndpoint/0"

MEANING = {
    "domain_context": None,
    "nodes": [
        {"id": "svc:shop", "kind": "service", "name": "shop", "modules": ["shop"],
         "evidence": [{"file": "docker-compose.yml", "line": 2}]},
        {"id": "svc:worker", "kind": "service", "name": "worker", "modules": ["worker"],
         "evidence": [{"file": "docker-compose.yml", "line": 3}]},
        {"id": "lib:common", "kind": "library", "name": "common", "modules": ["common", "pylib", "scripts"]},
        {"id": "db:postgres:DB_HOST", "kind": "datastore", "name": "postgres"},
        {"id": "db:postgres:DB_HOST/public.orders", "kind": "table", "parent": "db:postgres:DB_HOST",
         "name": "public.orders"},
    ],
    "relations": [
        {"kind": "request", "from": "svc:worker", "to": "shop::io.demo.shop.api.OrderApi$#createEndpoint/0",
         "key": "POST /v1/orders/create", "confidence": "inferred",
         "why": "worker posts to SHOP_URL; compose names the shop service but the URL is set per deployment",
         "deployment_dependent": True,
         "evidence": [{"file": "worker/main.py", "line": 13},
                      {"file": "shop/src/main/scala/io/demo/shop/api/OrderApi.scala", "line": 4}]},
        {"kind": "request", "from": "svc:worker", "to": "shop::io.demo.shop.api.OrderApi$#getEndpoint/0",
         "key": "GET /v1/orders/{id}", "confidence": "confirmed", "via": "pylib::pylib.client#call/0",
         "evidence": [{"file": "pylib/client.py", "line": 4},
                      {"file": "shop/src/main/scala/io/demo/shop/api/OrderApi.scala", "line": 10}]},
        {"kind": "db-write", "from": "shop::io.demo.shop.repo.PgOrderRepo#save/2",
         "to": "db:postgres:DB_HOST/public.orders", "key": "table public.orders", "confidence": "confirmed",
         "evidence": [{"file": "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala", "line": 11}]},
    ],
    "pins": [{"id": "worker-job-creates-an-order", "title": "worker job creates an order", "start": RUN,
              "direction": "downstream", "by": "agent"}],
    "unpinned": [],
    "examples": {"types": {}, "entries": [
        {"node": RUN, "key": "POST /v1/work/run/{job_id}", "request": {"job_id": "job-42", "dry": False},
         "response": {"ok": "201"}},
        {"node": HEALTH, "key": "GET /health", "request": {}, "response": "ok"},
        {"node": CREATE, "key": "POST /v1/orders/create", "request": {"job": "job-42"},
         "response": {"id": "ord-42", "total": "19.90"}},
        {"node": GET, "key": "GET /v1/orders/{id}", "request": {"id": "ord-42"},
         "response": {"id": "ord-42", "total": "19.90"}},
    ]},
    "problems": [{"text": "SHOP_URL value is per deployment", "nodes": ["svc:worker"], "source": "agent"}],
    "summaries": {"worker::worker.main#run/2": "Runs a job by asking shop to create an order."},
}
