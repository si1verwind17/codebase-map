from vizcode import facts, routes, stack


def test_sql_reads_and_writes():
    q = facts.sql_facts("INSERT INTO public.jobs (name) SELECT name FROM staging.jobs")
    assert q == {"verb": "insert", "reads": ["staging.jobs"], "writes": ["public.jobs"]}
    q = facts.sql_facts("DELETE FROM public.jobs WHERE id IN (SELECT id FROM public.old)")
    assert q["writes"] == ["public.jobs"] and q["reads"] == ["public.old"]
    q = facts.sql_facts("select * from information_schema.tables t join public.users u on 1=1")
    assert q["reads"] == ["public.users"]
    assert facts.sql_facts("INSERT INTO {table} (a) VALUES (1)")["writes"] == []


def test_an_interpolated_table_name_is_no_table():
    for text in ("SELECT n FROM {table('events')} WHERE x > 1", "SELECT n FROM ${tbl} WHERE x > 1",
                 "SELECT n FROM #{tbl} WHERE x > 1", "SELECT n FROM %s WHERE x > 1",
                 "SELECT n FROM %(tbl)s WHERE x > 1", "SELECT n FROM ? WHERE x > 1", "SELECT n FROM :tbl",
                 "SELECT n FROM app.{tbl} JOIN app.${other} ON 1=1", "SELECT n FROM events_%s",
                 "SELECT n FROM events_#{day} JOIN app.%(t)s ON 1=1", "SELECT n FROM ",
                 "INSERT INTO {table} (a) VALUES (1)", "UPDATE ${t} SET a = 1", "UPDATE %s SET a = 1", "UPDATE ? SET a = 1",
                 "DELETE FROM app.%s"):
        assert facts.sql_facts(text)["reads"] == facts.sql_facts(text)["writes"] == [], text
    q = facts.sql_facts("SELECT n FROM {tbl} JOIN orders o ON o.id = n")
    assert q["reads"] == ["orders"]
    assert facts.sql_facts("INSERT INTO ${t} (a) SELECT a FROM staging")["writes"] == []


def test_prose_is_not_sql():
    assert facts.sql_facts("Select the job from the queue.") is None
    assert facts.sql_facts("the job is selected from the queue") is None
    assert facts.sql_facts("Updates the cache") is None
    assert facts.sql_facts("select 1") is None


def test_prose_that_starts_like_sql_names_no_table():
    for text in ("Update line prior unit price amount.", "Update translation", "update date.",
                 "Create order from existing cart.", "Create or update line discount for the order.",
                 "Delete any event found in DB for old orders.", "Delete stale rows from database that are older.",
                 "Truncate text to a safe length.", "Merge two accounts into one", "merge FROM TO",
                 "Select products from all warehouses", "Update empty args with defaults from argument definition."):
        assert facts.sql_facts(text) is None, text


def test_sql_keywords_and_cte_names_are_no_tables():
    q = facts.sql_facts("SELECT id, email FROM jobs FOR UPDATE SKIP LOCKED LIMIT 1")
    assert q == {"verb": "select", "reads": ["jobs"], "writes": []}
    q = facts.sql_facts("CREATE TRIGGER t BEFORE INSERT OR UPDATE ON orders FOR EACH ROW EXECUTE PROCEDURE f()")
    assert q is None or "ON" not in q["writes"] + q["reads"]
    q = facts.sql_facts("WITH recent AS (SELECT id FROM orders LIMIT 5) UPDATE orders o SET seen = true "
                        "FROM recent WHERE o.id = recent.id")
    assert q == {"verb": "with", "reads": ["orders"], "writes": ["orders"]}
    q = facts.sql_facts("SELECT extract(epoch FROM created_at), x FROM orders o WHERE a IS DISTINCT FROM b")
    assert q["reads"] == ["orders"]
    assert facts.sql_facts('SELECT * FROM "order" WHERE id = 1')["reads"] == ["order"]   # quoted: a name
    assert facts.sql_facts("UPDATE orders SET a = 1")["writes"] == ["orders"]
    assert facts.sql_facts("truncate table jobs")["writes"] == ["jobs"]


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


def test_tapir_chain_after_an_indented_line_and_through_a_method_prefix():
    vals = dict([
        routes.tapir_val(["Base"], "base", "endpoint"),
        routes.tapir_val(["Base", "V1"], "v1", 'base.in("v1")'),
        routes.tapir_val(["Base", "V1"], "check", 'v1.in("check")'),
        routes.tapir_val(["Base", "V1"], "apply", "check", key="Base.V1"),   # `object V1 { def apply() = check }`
    ])
    resolved = routes.resolve_tapir(vals)
    assert resolved["Base.V1"] == ["v1", "check"]
    body = '{\n    import a.b.C\n    given Schema[In] = Schema.derived\n    Base.V1().post.in(jsonBody[In]).out(jsonBody[Out])\n  }'
    assert routes.tapir_uses(body, resolved) == [("POST", "/v1/check")]
    assert routes.tapir_uses("x\n    Base.V1.check.get", resolved) == [("GET", "/v1/check")]   # words stay apart
    assert routes.tapir_uses("Base.V1.apply().post.in(jsonBody[In])", resolved) == [("POST", "/v1/check")]


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


def test_tapir_prefix_that_adds_errors_headers_and_security():
    """A shared base endpoint adds an error output, headers or a security input before any path: still a prefix."""
    vals = dict([routes.tapir_val(["Http"], "baseEndpoint",
                                  'endpoint\n  .errorOut(failOutput)\n  // see https://example.org/x\n'
                                  '  .out(header("X-Frame-Options", "DENY")) /* the base */'),
                 routes.tapir_val(["Http"], "secureEndpoint",
                                  'baseEndpoint.securityIn(auth.bearer[String]().map(_.asId[T])(_.toString))'),
                 routes.tapir_val(["Api"], "v1", 'baseEndpoint.in("api" / "v1").in(header[String]("X-Trace"))')])
    resolved = routes.resolve_tapir(vals)
    assert resolved == {"Http.baseEndpoint": [], "Http.secureEndpoint": [], "Api.v1": ["api", "v1"]}
    assert routes.tapir_uses('baseEndpoint.post.in("user" / "register").out(jsonBody[Out])', resolved) == [
        ("POST", "/user/register")]
    assert routes.tapir_uses('secureEndpoint[ApiKey].get.in("user").out(jsonBody[Out])', resolved) == [
        ("GET", "/user")]
    # a path segment written as the file's string constant
    assert routes.tapir_uses('baseEndpoint.post.in(UserPath / "login").out(jsonBody[Out])', resolved,
                             {"UserPath": "user"}) == [("POST", "/user/login")]
    # a value that is no endpoint never becomes one, nor does a layer built by calls
    assert routes.tapir_val(["X"], "f", 'filters.contains(x)') is None
    assert routes.tapir_val(["X"], "live", 'ZLayer.fromFunction(Live.apply)') is None


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


def test_sql_written_out_as_text_is_no_database_access(make_repo):
    from vizcode import structure
    repo = make_repo({
        "tools/requirements.txt": "",
        "tools/gen_seed.py": 'import json\n\nfor row in json.load(open("rows.json")):\n'
                             '    print(f"INSERT INTO items (id) VALUES ({row})")\n',
        "tools/dump.py": 'def dump(out, rows):\n    for r in rows:\n'
                         '        out.write("INSERT INTO items (id) VALUES (%s);" % r)\n',
        "tools/store.py": 'def save(cur, row):\n    print("saving", row)\n'
                          '    cur.execute("INSERT INTO items (id) VALUES (%s)", (row,))\n',
        "tools/queries.py": 'LOAD = "SELECT id FROM items WHERE id = %s"\n'})
    sql = {f: ff["sql"] for f, ff in structure.build(repo, "docs/viz-code")["facts"].items()}
    assert sql["tools/gen_seed.py"] == [] and sql["tools/dump.py"] == []
    assert sql["tools/store.py"][0]["writes"] == ["items"]
    assert sql["tools/queries.py"][0]["reads"] == ["items"]


def test_interpolated_table_names_stay_out_of_the_facts(make_repo):
    from vizcode import structure
    repo = make_repo({
        "jobs/requirements.txt": "",
        "jobs/py_job.py": 'def load(read, table):\n'
                          '    return read(f"SELECT n FROM {table(\'events\')} WHERE n > 1")\n',
        "jobs/fmt_job.py": 'def load(cur, name):\n    cur.execute("SELECT n FROM %s WHERE n > 1" % name)\n',
        "web/package.json": "{}",
        "web/load.js": "export function load(db, tbl) {\n  return db.query(`SELECT n FROM ${tbl} WHERE n > 1`);\n}\n",
        "rb/Gemfile": "",
        "rb/load.rb": 'def load(db, tbl)\n  db.exec("SELECT n FROM #{tbl} WHERE n > 1")\nend\n'})
    sql = {f: ff["sql"] for f, ff in structure.build(repo, "docs/viz-code")["facts"].items() if ff["sql"]}
    assert set(sql) == {"jobs/py_job.py", "jobs/fmt_job.py", "web/load.js", "rb/load.rb"}   # still code that runs SQL
    assert {t for qs in sql.values() for q in qs for t in q["reads"] + q["writes"]} == set()
