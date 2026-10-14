from vizcode import facts, routes, stack


def test_sql_reads_and_writes():
    q = facts.sql_facts("INSERT INTO public.jobs (name) SELECT name FROM staging.jobs")
    assert q == {"verb": "insert", "reads": ["staging.jobs"], "writes": ["public.jobs"]}
    q = facts.sql_facts("DELETE FROM public.jobs WHERE id IN (SELECT id FROM public.old)")
    assert q["writes"] == ["public.jobs"] and q["reads"] == ["public.old"]
    q = facts.sql_facts("select * from information_schema.tables t join public.users u on 1=1")
    assert q["reads"] == ["public.users"]
    assert facts.sql_facts("INSERT INTO {table} (a) VALUES (1)")["writes"] == ["{table}"]


def test_prose_is_not_sql():
    assert facts.sql_facts("Select the job from the queue.") is None
    assert facts.sql_facts("the job is selected from the queue") is None
    assert facts.sql_facts("Updates the cache") is None
    assert facts.sql_facts("select 1") is None


def test_urls():
    assert facts.url_facts("{BASE}/v1/orders/create") == ["/v1/orders/create"]
    assert facts.url_facts("wss://stream.example.com/ws?x=1") == ["wss://stream.example.com/ws?x=…"]
    assert facts.url_facts("see the /tmp/file") == []


def test_fastapi():
    assert routes.fastapi_decorator('@router.post("/run/{id}")') == ("router", "POST", "/run/{id}")
    assert routes.fastapi_decorator("@app.websocket('/ws')") == ("app", "WS", "/ws")
    assert routes.fastapi_decorator("@lru_cache()") is None
    src = 'app = FastAPI()\nrouter = APIRouter(\n    prefix="/v1/x", tags=["x"])\n'
    assert routes.fastapi_prefixes(src) == {"app": "", "router": "/v1/x"}


def test_tapir_chain_resolution():
    vals = dict([
        routes.tapir_val(["Base"], "base", "endpoint"),
        routes.tapir_val(["Base", "V1"], "v1", 'base.in("v1")'),
        routes.tapir_val(["Base", "V1", "Orders"], "orders", 'v1.in("orders")'),
        routes.tapir_val(["Base", "V1", "Orders"], "create", 'orders\n  .in("create")'),
        routes.tapir_val(["Other"], "x", "somethingElse"),
    ])
    resolved = routes.resolve_tapir(vals)
    assert resolved["Base.V1.Orders.create"] == ["v1", "orders", "create"]
    assert "Other.x" not in resolved
    body = 'BaseX.y\nBase.V1.Orders\n .create\n .post\n .in(path[String]("id")).in("items")\n'
    assert routes.tapir_uses(body, resolved) == [("POST", "/v1/orders/create/{id}/items")]
    assert routes.tapir_uses("m.get(1)", resolved) == []


def test_ziohttp():
    src = 'val r = Routes(\n  Method.GET / "v1" / "users" / string("id") -> handler(x),\n  Method.POST / Root / "v1/users" -> h)\n'
    got = stack.find_routes(stack.load(None), "scala", src, ["zio.http"], [], "f")
    assert [(r["method"], r["path"], r["line"]) for r in got] == [("GET", "/v1/users/{id}", 2), ("POST", "/v1/users", 3)]


def test_url_literals_drop_credentials_and_query_strings():
    urls = facts.url_facts('a = "https://bot:s3cr3t@hooks.example.com/api/v1/send?token=abc&x=1"')
    assert urls == ["https://***@hooks.example.com/api/v1/send?token=…&x=…"]
    assert facts.url_facts('b = "wss://stream.example.com/ws"') == ["wss://stream.example.com/ws"]


def test_structure_keeps_no_url_secret_anywhere(make_repo):
    import json
    from vizcode import structure
    repo = make_repo({"app/__init__.py": "", "app/hook.py": 'URL = "https://bot:s3cr3t@hooks.example.com/api/v1/send?token=abc"\n'})
    s = structure.build(repo, "docs/viz-code")
    text = json.dumps(s)
    assert "hooks.example.com" in text and "s3cr3t" not in text and "token=abc" not in text


# --- tapir forms from the parking-city demo (pricing, billing, reservations) ---

def test_tapir_endpoint_root_with_slash_paths_and_query_inputs():
    quote = ('endpoint.get\n      .in("v1" / "quote")\n      .in(query[String]("zone"))\n'
             '      .in(query[Int]("minutes"))\n      .out(jsonBody[QuoteView])\n'
             '      .errorOut(statusCode(StatusCode.NotFound).and(jsonBody[PricingError]))')
    settle = 'endpoint.post\n      .in("internal" / "settle")\n      .out(jsonBody[SettleResult])\n      .errorOut(stringBody)'
    root = {"endpoint": []}
    assert routes.tapir_uses(quote, root) == [("GET", "/v1/quote")]
    assert routes.tapir_uses(settle, root) == [("POST", "/internal/settle")]
    assert routes.tapir_uses('endpoint.get("k")', root) == []       # a map lookup, not tapir


def test_a_field_named_like_an_endpoint_is_no_route():
    resolved = {"BaseEndpoint.V1.Order.filters": ["v1", "order", "filters"]}
    # a case class field `filters: Option[String]` that shares the endpoint's last name
    assert routes.tapir_uses("filters.contains(SimOptions.Exchange)", resolved) == []
    # a step tapir has that no list names, before the method: still an endpoint
    assert routes.tapir_uses("filters.in(\"a\").errorOutVariantsFromCurrent(c => c).post.out(jsonBody[R])", resolved) == [
        ("POST", "/v1/order/filters/a")]
    assert routes.tapir_uses("filters.in(query[String](\"symbol\")).out(jsonBody[R])", resolved) == [
        ("GET", "/v1/order/filters")]


def test_tapir_shared_base_val_with_slash_paths():
    vals = dict([routes.tapir_val(["ReservationEndpoints"], "base", 'endpoint.in("v1" / "reservations")')])
    resolved = routes.resolve_tapir(vals)
    assert resolved["ReservationEndpoints.base"] == ["v1", "reservations"]
    create = 'base.post\n      .in(jsonBody[NewReservation])\n      .out(statusCode(StatusCode.Created).and(jsonBody[Reservation]))'
    get = 'base.get\n      .in(path[UUID]("id"))\n      .out(jsonBody[Reservation])\n      .errorOut(errors)'
    cancel = 'base.post\n      .in(path[UUID]("id") / "cancel")\n      .out(jsonBody[Reservation])'
    assert routes.tapir_uses(create, resolved) == [("POST", "/v1/reservations")]
    assert routes.tapir_uses(get, resolved) == [("GET", "/v1/reservations/{id}")]
    assert routes.tapir_uses(cancel, resolved) == [("POST", "/v1/reservations/{id}/cancel")]
    # a val that already picks a method is an endpoint, not a prefix
    assert routes.tapir_val(["X"], "e", 'base.get.in(path[UUID]("id"))') is None


def test_tapir_method_after_inputs_and_method_less_endpoint():
    root = {"endpoint": []}
    # scala-zio example HealthCheck.scala: the method comes after the path
    health = 'endpoint.in("health")\n    .get.out(stringBody)'
    assert routes.tapir_uses(health, root) == [("GET", "/health")]
    # no method at all: tapir's default, GET
    assert routes.tapir_uses('endpoint.in("v1" / "ping").out(stringBody)', root) == [("GET", "/v1/ping")]
    # a bare prefix or a path-only chain is not an endpoint by itself
    assert routes.tapir_uses('endpoint.in("v1")', root) == []
    assert routes.tapir_uses('f(endpoint.in("a").out(stringBody))', root) == []
