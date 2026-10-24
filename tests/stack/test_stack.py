"""stack.py: packs plus stack.yaml, path readers, route patterns."""
import hashlib
import json

import pytest
import yaml

from vizcode import stack

OLD_SINKS = [
    ("python", "psycopg", "sql-db"),
    ("python", "psycopg2", "sql-db"),
    ("python", "asyncpg", "sql-db"),
    ("python", "sqlalchemy", "sql-db"),
    ("python", "sqlite3", "sql-db"),
    ("python", "pymssql", "sql-db"),
    ("python", "pymysql", "sql-db"),
    ("python", "mysql.connector", "sql-db"),
    ("python", "pyodbc", "sql-db"),
    ("python", "google.cloud.bigquery", "sql-db"),
    ("python", "pyspark", "spark"),
    ("python", "pymongo", "doc-db"),
    ("python", "motor", "doc-db"),
    ("python", "redis", "cache"),
    ("python", "requests", "http-out"),
    ("python", "httpx", "http-out"),
    ("python", "aiohttp", "http"),
    ("python", "urllib.request", "http-out"),
    ("python", "fastapi", "http-in"),
    ("python", "flask", "http-in"),
    ("python", "websockets", "ws"),
    ("python", "websocket", "ws"),
    ("python", "kafka", "event"),
    ("python", "confluent_kafka", "event"),
    ("python", "aiokafka", "event"),
    ("python", "pika", "event"),
    ("python", "aio_pika", "event"),
    ("python", "grpc", "grpc"),
    ("python", "boto3", "cloud-sdk"),
    ("python", "google.cloud.storage", "cloud-sdk"),
    ("scala", "io.getquill", "sql-db"),
    ("scala", "doobie", "sql-db"),
    ("scala", "skunk", "sql-db"),
    ("scala", "slick", "sql-db"),
    ("scala", "scalikejdbc", "sql-db"),
    ("scala", "zio.jdbc", "sql-db"),
    ("scala", "java.sql", "sql-db"),
    ("scala", "org.apache.spark", "spark"),
    ("scala", "sttp.client3", "http-out"),
    ("scala", "sttp.client4", "http-out"),
    ("scala", "sttp.tapir", "http-in"),
    ("scala", "zio.http", "http"),
    ("scala", "zio.kafka", "event"),
    ("scala", "fs2.kafka", "event"),
    ("scala", "org.apache.kafka", "event"),
    ("scala", "dev.profunktor.redis4cats", "cache"),
    ("scala", "zio.redis", "cache"),
    ("scala", "io.grpc", "grpc"),
    ("scala", "scalapb", "grpc"),
    ("scala", "software.amazon.awssdk", "cloud-sdk"),
]

FLASK = (r"@\w+\.route\(\s*[\"'](?P<path>[^\"']*)[\"'](?:[^)]*methods\s*=\s*\[(?P<methods>[^\]]*)\])?")


def flask_stack(tmp_path, extra=""):
    return stack.load(write(tmp_path, "python:\n  routes:\n    - name: flask\n      when: flask\n      path: literal\n"
                            "      method: GET\n      regex: '" + FLASK.replace("'", "''") + "'\n" + extra))


def test_packs_hold_every_old_sink():
    st = stack.load(None)
    got = [(lang, p, k) for lang, es in st.imports.items() for p, k, src in es
           if src == "pack" and lang in ("python", "scala")]   # the other languages' packs: test_packs_jvm and later
    new = [("python", "google.cloud.pubsub", "event"), ("python", "google.cloud.pubsub_v1", "event"),
           ("python", "sqlmodel", "sql-db"), ("python", "quart", "http-in")]
    assert sorted(got) == sorted(OLD_SINKS + new) and len(OLD_SINKS) == 50


def test_same_kind_is_not_override(tmp_path):
    st = stack.load(write(tmp_path, "python:\n  imports:\n    - {prefix: flask, kind: http-in}\n"))
    assert st.overrides == []
    assert stack.sink_kinds(st, "python", "flask") == [{"kind": "http-in", "lib": "flask"}]


def test_sink_kinds():
    st = stack.load(None)
    assert stack.sink_kinds(st, "python", "psycopg") == [{"kind": "sql-db", "lib": "psycopg"}]
    assert stack.sink_kinds(st, "scala", "io.getquill.PostgresZioJdbcContext") == [{"kind": "sql-db", "lib": "io.getquill"}]
    assert stack.sink_kinds(st, "python", "requestsx") == []
    assert stack.sink_kinds(st, "python", "pyspark.sql") == [{"kind": "spark", "lib": "pyspark"}]
    assert stack.sink_kinds(st, "python", "pymssql") == [{"kind": "sql-db", "lib": "pymssql"}]
    assert stack.sink_kinds(st, "python", "google.cloud.storage") == [{"kind": "cloud-sdk", "lib": "google.cloud.storage"}]
    assert stack.sink_kinds(st, "scala", "org.apache.spark.sql") == [{"kind": "spark", "lib": "org.apache.spark"}]


def test_stack_kind_overrides_pack(tmp_path):
    st = stack.load(write(tmp_path, "python:\n  imports:\n    - {prefix: redis, kind: doc-db}\n"))
    assert stack.sink_kinds(st, "python", "redis") == [{"kind": "doc-db", "lib": "redis"}]
    assert st.overrides == [{"lang": "python", "prefix": "redis", "pack_kind": "cache", "kind": "doc-db"}]


def test_stack_adds_import_and_covers(tmp_path):
    st = stack.load(write(tmp_path, "python:\n  imports:\n    - {prefix: celery, kind: event}\n  ignore: [pydantic]\n"))
    assert stack.sink_kinds(st, "python", "celery.app") == [{"kind": "event", "lib": "celery"}]
    assert stack.covered(st, "python", "celery.app") and stack.covered(st, "python", "pydantic")
    assert not stack.covered(st, "python", "marshmallow") and not stack.covered(st, "scala", "celery")
    assert stack.covered(st, "scala", "java.util") and not stack.covered(st, "scala", "javax2")
    st = flask_stack(tmp_path)
    assert stack.covered(st, "python", "flask.views")


@pytest.mark.parametrize("text, expect", [
    ("- a\n- b\n", "must be a mapping"),
    ("cobol:\n  imports: []\n", "unknown language 'cobol'"),
    ("python:\n  imports: {a: b}\n", "python.imports: must be a list"),
    ("python:\n  routez: []\n", "unknown group 'routez'"),
    ("python:\n  imports:\n    - {prefix: x}\n", "python.imports[0] (x): missing kind"),
    ("python:\n  imports:\n    - {prefix: x, kind: nosuch}\n", "unknown kind 'nosuch'"),
    ("python:\n  routes:\n    - {name: r, path: literal, method: GET}\n", "python.routes[0] (r): missing regex"),
    ("python:\n  routes:\n    - {name: r, path: literal, method: GET, regex: '(['}\n", "does not compile"),
    ("python:\n  routes:\n    - {name: r, path: literal, method: GET, regex: 'x'}\n", "no path group"),
    ("python:\n  routes:\n    - {name: r, path: literal, regex: '(?P<path>x)'}\n", "no method source"),
    ("python:\n  routes:\n    - {name: r, path: tree, method: GET, regex: '(?P<path>x)'}\n", "unknown path reader 'tree'"),
    ("python:\n  routes:\n    - {name: r, path: literal, method: GET, regex: '(?P<path>x)'}\n"
     "    - {name: r, path: literal, method: GET, regex: '(?P<path>y)'}\n", "python.routes[1] (r): duplicate route name"),
    ("scala:\n  effects:\n    - {name: X, match: value}\n", "scala.effects[0] (X): unknown match 'value'"),
    ("python:\n  routes:\n    - {name: fastapi, path: literal, method: GET, regex: '(?P<path>x)'}\n",
     "python.routes[0] (fastapi): clashes with a built-in rule"),
    ("scala:\n  routes:\n    - {name: tapir, path: literal, method: GET, regex: '(?P<path>x)'}\n",
     "scala.routes[0] (tapir): clashes with a built-in rule"),
    ("scala:\n  routes:\n    - {name: tapir-client, path: literal, method: GET, regex: '(?P<path>x)'}\n",
     "clashes with a built-in rule"),
    ("python:\n  effects: [Task]\n", "python.effects: effects are Scala only for now"),
    ("exclude: gen/*\n", "exclude: must be a list of globs"),
    ("exclude: ['']\n", "exclude: must be a list of globs"),
])
def test_load_errors(tmp_path, text, expect):
    with pytest.raises(stack.StackError) as e:
        stack.load(write(tmp_path, text))
    assert "stack.yaml: " in str(e.value) and expect in str(e.value)


def test_load_crlf_bom(tmp_path):
    text = "python:\r\n  imports:\r\n    - {prefix: celery, kind: event}\r\n"
    st = stack.load(write(tmp_path, "", raw=b"\xef\xbb\xbf" + text.encode()))
    assert stack.sink_kinds(st, "python", "celery") == [{"kind": "event", "lib": "celery"}]


def test_no_stack_file(tmp_path):
    for arg in (None, tmp_path / "missing.yaml"):
        st = stack.load(arg)
        assert st.digest is None and st.overrides == [] and st.patterns[0].source == "pack"
        assert all(src == "pack" for es in st.imports.values() for _, _, src in es)


def content_digest(path):
    return hashlib.sha256(json.dumps(yaml.safe_load(path.read_text()), sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def test_digest_is_sha256_of_parsed_content(tmp_path):
    p = write(tmp_path, "python: {}\n")
    assert stack.load(p).digest == content_digest(p)
    q = tmp_path / "commented.yaml"
    q.write_text("# a note\npython:   {}   # none yet\n\n")
    assert stack.load(q).digest == stack.load(p).digest
    q.write_text("python: {ignore: [a]}\n")
    assert stack.load(q).digest != stack.load(p).digest


def test_effect_names(tmp_path):
    types, values = stack.effect_names(stack.load(None), "scala")
    assert "IO" in types and "ZIO" in values and stack.effect_names(stack.load(None), "python") == ((), ())
    st = stack.load(write(tmp_path, "scala:\n  effects: [Resource, {name: Future, match: type}]\n"))
    types, values = stack.effect_names(st, "scala")
    assert "Future" in types and "Future" not in values and "Resource" in values


def test_normalise():
    assert stack.normalise("/users/<int:id>/") == "/users/{id}"
    assert stack.normalise("users/<id>") == "/users/{id}"
    assert stack.normalise("/a/:id") == "/a/{id}"
    assert stack.normalise("/a/{id}") == "/a/{id}"
    assert stack.normalise("/") == "/" and stack.normalise("") == "/"


@pytest.mark.parametrize("raw", ["/items/{id:int}", "/items/{id?}", "/items/{id:minlength(1)}", "/items/{id:[0-9]+}",
                                 "/items/{id:int:min(1)}", "/items/{*id}", "/items/{**id}", "/items/{id...}",
                                 "/items/:id?", "/items/:id(\\d+)", "/items/<path:id>"])
def test_normalise_drops_constraints_and_markers(raw):
    # one key per route whatever the framework writes around a parameter's name
    assert stack.normalise(raw) == "/items/{id}"


def test_read_path_segments():
    assert stack.read_path('Root / "users" / IntVar(id)', "segments") == "/users/{id}"
    assert stack.read_path('Root / "v1/quote"', "segments") == "/v1/quote"
    assert stack.read_path('"v1" / long("id") / "x"', "segments") == "/v1/{id}/x"
    assert stack.read_path('Root / "a" / name', "segments") == "/a/{name}"
    assert stack.read_path("Root", "segments") == "/"
    assert stack.read_path("/users/<int:id>", "literal") == "/users/{id}"


def test_find_routes_flask(tmp_path):
    st = flask_stack(tmp_path)
    src = '@bp.route("/users/<int:id>", methods=["GET", "POST"])\ndef user(id): ...\n'
    got = stack.find_routes(st, "python", src, ["flask"], [(2, 2, "f#user")], "f")
    assert got == [{"method": m, "path": "/users/{id}", "handler": "f#user", "line": 1, "framework": "flask",
                    "source": "stack.yaml", "on": "bp"} for m in ("GET", "POST")]
    got = stack.find_routes(st, "python", '@app.route("/x/")\ndef x(): ...\n', ["flask"], [], "f")
    assert [(r["method"], r["path"], r["handler"]) for r in got] == [("GET", "/x", "f")]


def test_find_routes_when(tmp_path):
    st = flask_stack(tmp_path)
    src = '@bp.route("/a")\ndef a(): ...\n'
    assert stack.find_routes(st, "python", src, ["django.urls"], [], "f") == []
    assert stack.find_routes(st, "python", src, ["flask.views"], [], "f") != []
    assert stack.find_routes(st, "scala", src, ["flask"], [], "f") == []


def test_handler_innermost_then_next_then_file(tmp_path):
    st = flask_stack(tmp_path)
    src = 'x = 1\n@a.route("/a")\n@a.route("/b")\ndef f(): ...\n'
    spans = [(1, 10, "outer"), (3, 6, "inner")]
    hs = {r["path"]: r["handler"] for r in stack.find_routes(st, "python", src, ["flask"], spans, "file")}
    assert hs == {"/a": "outer", "/b": "inner"}
    hs = stack.find_routes(st, "python", src, ["flask"], [(4, 4, "f")], "file")
    assert {r["handler"] for r in hs} == {"f"}


def test_method_group_upper_cased_and_falls_back(tmp_path):
    st = stack.load(write(tmp_path, "python:\n  routes:\n    - name: r\n      path: literal\n      method: ANY\n"
                          "      regex: '(?P<method>get|post)?\\s*(?P<path>/\\w+)'\n"))
    got = stack.find_routes(st, "python", "get /a\n/b\n", [], [], "f")
    assert [(r["method"], r["path"]) for r in got] == [("GET", "/a"), ("ANY", "/b")]


def test_empty_path_match_skipped(tmp_path):
    st = stack.load(write(tmp_path, "python:\n  routes:\n    - name: r\n      path: literal\n      method: GET\n"
                          "      regex: 'route\\((?P<path>[^)]*)\\)'\n"))
    got = stack.find_routes(st, "python", "route()\nroute(/a)\n", [], [], "f")
    assert [(r["path"], r["line"]) for r in got] == [("/a", 2)]


def test_pack_ziohttp():
    src = 'val r = Routes(\n  Method.GET / "v1" / "users" / string("id") -> handler(x),\n  Method.POST / Root / "v1/users" -> h)\n'
    got = stack.find_routes(stack.load(None), "scala", src, ["zio.http"], [], "f")
    assert [(r["method"], r["path"], r["line"], r["framework"], r["source"]) for r in got] == [
        ("GET", "/v1/users/{id}", 2, "zio-http", "pack"), ("POST", "/v1/users", 3, "zio-http", "pack")]


def test_ensure_header(tmp_path):
    p = write(tmp_path, "python:\n  ignore: [a]\n")
    stack.ensure_header(p)
    text = p.read_text()
    assert text == stack.HEADER + "python:\n  ignore: [a]\n"
    stack.ensure_header(p)
    assert p.read_text() == text
    assert stack.load(p).digest


def test_segments_capture_names_match_old_reader():
    assert stack.read_path('Root / "u" / string("user-id")', "segments") == "/u/{user-id}"
    assert stack.read_path('Root / "u" / long("a.b")', "segments") == "/u/{a.b}"
    pack = stack.load(None)
    for src, want in [('val r = Routes(\n  Method.GET / "v1" / "users" / string("id") -> handler(x),\n'
                       '  Method.POST / Root / "v1/users" -> h)\n', [("GET", "/v1/users/{id}"), ("POST", "/v1/users")]),
                      ('Method.GET / Root / "u" / string("user-id") -> h\n', [("GET", "/u/{user-id}")])]:
        got = [(r["method"], r["path"]) for r in stack.find_routes(pack, "scala", src, ["zio.http"], [], "f")]
        assert got == want


def test_invalid_utf8_is_stack_error(tmp_path):
    with pytest.raises(stack.StackError, match="stack.yaml: not valid UTF-8"):
        stack.load(write(tmp_path, "", raw=b"python:\n  ignore: [\xff]\n"))


# --- the scanner reads the Stack (fixtures: quart_repo, http4s_repo) -------------------------------------------

import subprocess
import sys
from pathlib import Path

from helpers import write
from conftest import QUART_STACK, HTTP4S_STACK, with_stack

from vizcode import roles, structure

EXTRACT = Path(__file__).resolve().parents[2] / "skills" / "visualizing-codebases" / "scripts" / "extract.py"


def route_set(s, lang_ext):
    return {(r["method"], r["path"], r["handler"]) for f, ff in s["facts"].items() if f.endswith(lang_ext)
            for r in ff["routes"]}


def test_quart_routes_with_stack(quart_repo):
    with_stack(quart_repo, QUART_STACK)
    s = structure.build(quart_repo, "docs/viz-code")
    users = "shopfront::shopfront.users"
    assert route_set(s, ".py") == {
        ("GET", "/users/{id}", f"{users}#user/1"), ("DELETE", "/users/{id}", f"{users}#user/1"),
        ("POST", "/users", f"{users}#create_user/0"), ("GET", "/users", f"{users}#list_users/0"),
        ("GET", "/health", "shopfront::shopfront.__init__#health/0"), ("GET", "/ping", "shopfront::shopfront.wsgi")}
    sinks = {x["kind"] + ":" + x["lib"] for x in s["facts"]["shopfront/tasks.py"]["sinks"]}
    assert {"event:celery", "http-out:requests"} <= sinks
    r = roles.package_roles(s["nodes"], s["files"], s["facts"])
    assert r["shopfront::shopfront/"] == "entry"
    assert {x["source"] for f in s["facts"].values() for x in f["routes"]} == {"stack.yaml"}
    assert s["stack"]["digest"] == content_digest(quart_repo / "docs/viz-code/stack.yaml")


def test_handler_falls_back_to_file(quart_repo):
    with_stack(quart_repo, QUART_STACK)
    s = structure.build(quart_repo, "docs/viz-code")
    ping = next(r for r in s["facts"]["shopfront/wsgi.py"]["routes"] if r["path"] == "/ping")
    assert ping["handler"] == s["files"]["shopfront/wsgi.py"]["node"]


def test_quart_without_stack_has_no_routes(quart_repo):
    s = structure.build(quart_repo, "docs/viz-code")
    assert route_set(s, ".py") == set()
    assert s["stack"]["digest"] is None


def test_http4s_with_stack(http4s_repo):
    with_stack(http4s_repo, HTTP4S_STACK)
    s = structure.build(http4s_repo, "docs/viz-code")
    pkg = "users::acme.users"
    routes_val = f"{pkg}.UserRoutes#routes/0"
    assert route_set(s, ".scala") == {("GET", "/users/{id}", routes_val), ("POST", "/users", routes_val)}
    methods = {n["id"] for n in s["nodes"] if n["kind"] == "method"}
    assert {f"{pkg}.UserRepo#count/0", f"{pkg}.Main$#server/0", routes_val} <= methods
    assert "sql-db:doobie" in {x["kind"] + ":" + x["lib"] for x in s["facts"]["users/src/main/scala/acme/users/UserRepo.scala"]["sinks"]}
    reads = {t for q in s["facts"]["users/src/main/scala/acme/users/UserRepo.scala"]["sql"] for t in q["reads"]}
    assert reads == {"users"}


def test_http4s_without_stack(http4s_repo):
    s = structure.build(http4s_repo, "docs/viz-code")
    assert route_set(s, ".scala") == set()
    pkg = "users::acme.users"
    methods = {n["id"] for n in s["nodes"] if n["kind"] == "method"}
    assert f"{pkg}.UserRepo#count/0" in methods
    assert f"{pkg}.Main$#server/0" not in methods and f"{pkg}.UserRoutes#routes/0" not in methods


def run_extract(repo):
    return subprocess.run([sys.executable, str(EXTRACT), str(repo)], capture_output=True, text=True)


def test_stack_error_exit(quart_repo):
    with_stack(quart_repo, "python:\n  imports:\n    - {prefix: celery, kind: nonsense}\n")
    p = run_extract(quart_repo)
    assert p.returncode == 2
    assert "celery" in p.stderr and "Traceback" not in p.stderr


def test_extract_adds_header(quart_repo):
    path = with_stack(quart_repo, "python:\n  ignore: [marshmallow]\n")
    p = run_extract(quart_repo)
    assert p.returncode == 0, p.stderr
    assert path.read_text().startswith(stack.HEADER)
    s = json.loads((quart_repo / "docs/viz-code/structure.json").read_text())
    assert s["stack"]["digest"] == content_digest(path)


def stack_section(md):
    return md.split("## Stack", 1)[1].split("\n## mod:", 1)[0] if "## Stack" in md else ""


def unrecognised(s):
    return {u["prefix"] for u in s["stack"]["unrecognised"]}


def test_report_quart_without_stack(quart_repo):
    s = structure.build(quart_repo, "docs/viz-code")
    rep = s["stack"]
    assert unrecognised(s) == {"celery", "marshmallow"}
    assert [(x["lang"], x["prefix"], x["kind"], x["files"]) for x in rep["servers_without_routes"]] == \
        [("python", "quart", "http-in", 3)]
    # the server files' decorator lines are listed too: what the missing route pattern has to read
    assert [(x["file"], x["lines"]) for x in rep["routes_unmatched"]] == [
        ("shopfront/__init__.py", [6]), ("shopfront/users.py", [6, 11, 16])]
    assert [(p["name"], p["matches"]) for p in rep["patterns"]] == [("celery-task", 1), ("celery-send-task", 0)]
    assert stack.count(rep) == 5
    md = structure.summary_md(s)
    assert "## Stack — 2 unrecognised imports, 1 server library without routes, 0 patterns with no match, " \
           "4 route-looking lines with no route\n" in md
    assert "- python `celery` — 1 file: shopfront/tasks.py:1" in md
    assert "- python `quart` (http-in) — 3 files import it; no route pattern matched in them" in md


def test_report_quart_with_stack(quart_repo):
    with_stack(quart_repo, QUART_STACK)
    s = structure.build(quart_repo, "docs/viz-code")
    rep = s["stack"]
    assert rep["unrecognised"] == [] and rep["servers_without_routes"] == []
    assert [(p["name"], p["source"], p["matches"]) for p in rep["patterns"]] == \
        [("quart", "stack.yaml", 4), ("quart-shortcut", "stack.yaml", 1), ("quart-rule", "stack.yaml", 1),
         ("celery-task", "pack", 1), ("celery-send-task", "pack", 0)]   # tasks.py's Celery task
    md = structure.summary_md(s)
    assert "## Stack — nothing unrecognised\n" in md
    assert "Route patterns:\n- python quart (stack.yaml): 4 routes in 1 file\n" in md
    assert "- python quart-shortcut (stack.yaml): 1 route in 1 file\n" in md
    assert "- python quart-rule (stack.yaml): 1 route in 1 file\n" in md
    assert stack.count(rep) == 0


def test_report_http4s_without_stack(http4s_repo):
    s = structure.build(http4s_repo, "docs/viz-code")
    assert unrecognised(s) == {"cats.effect", "io.circe", "org.http4s"}


def test_zero_match_flagged(quart_repo):
    with_stack(quart_repo, QUART_STACK + "    - name: dead\n      when: quart\n      path: literal\n"
               "      method: GET\n      regex: 'nomatch_(?P<path>x)'\n")
    s = structure.build(quart_repo, "docs/viz-code")
    dead = next(p for p in s["stack"]["patterns"] if p["name"] == "dead")
    assert dead["matches"] == 0 and dead["first_file"] == "shopfront/__init__.py:1"
    md = structure.summary_md(s)
    assert "## Stack — nothing unrecognised" not in md
    assert "## Stack — 0 unrecognised imports, 0 server libraries without routes, 1 pattern with no match\n" in md
    assert "- python dead (stack.yaml): 0 matches — check the regex against shopfront/__init__.py:1\n" in md
    assert stack.count(s["stack"]) == 1


def test_own_package_not_unrecognised(quart_repo):
    assert "shopfront" not in unrecognised(structure.build(quart_repo, "docs/viz-code"))


def test_stdlib_not_unrecognised(make_repo):
    repo = make_repo({
        "pyproject.toml": '[project]\nname = "a"\nversion = "0.1"\n',
        "a/__init__.py": "from __future__ import annotations\nimport os\nimport json\nimport os.path\n",
        "build.sbt": 'lazy val s = (project in file("s"))\n',
        "s/src/main/scala/x/A.scala": "package x\nimport scala.util.Try\nimport java.time.Instant\n\nobject A\n",
    })
    assert unrecognised(structure.build(repo, "docs/viz-code")) == set()


def test_extract_prints_stack_count(quart_repo):
    p = run_extract(quart_repo)
    assert json.loads(p.stdout)["stack"] == 5


def test_summary_stack_section_position(shop_repo):
    from vizcode import mapcheck
    s = structure.build(shop_repo, "docs/viz-code")
    md = structure.summary_md(s)
    assert md.index("Stats:") < md.index("## Stack") < md.index("## mod:")
    assert "SHOP_URL" in "; ".join(mapcheck.ENV_LINE.findall(md)).split("; ")


def test_overrides_in_summary(quart_repo):
    with_stack(quart_repo, "python:\n  imports:\n    - {prefix: requests, kind: http}\n")
    s = structure.build(quart_repo, "docs/viz-code")
    assert s["stack"]["overrides"] == [{"lang": "python", "prefix": "requests", "pack_kind": "http-out", "kind": "http"}]
    assert "Kinds changed by stack.yaml (1):\n- python `requests`: http-out → http\n" in structure.summary_md(s)


def test_built_in_route_rule_listed(shop_repo):
    s = structure.build(shop_repo, "docs/viz-code")
    got = {(p["lang"], p["name"], p["source"]) for p in s["stack"]["patterns"]}
    assert ("python", "fastapi", "built in") in got and ("scala", "tapir", "built in") in got


def test_scala_local_imports_not_unrecognised(make_repo):
    repo = make_repo({
        "build.sbt": 'lazy val s = (project in file("s"))\n',
        "s/src/main/scala/x/A.scala":
            "package x\nimport StripeFees.amountOf\nimport OrderExecution.*\nimport ctx.*\nimport zio.Scope\n"
            "import org.acme.lib.Thing\n\nobject A {\n  val ctx = 1\n  for { env <- f } yield { import env.* }\n}\n",
    })
    assert unrecognised(structure.build(repo, "docs/viz-code")) == {"org.acme"}


def test_python_sibling_and_generated_modules_internal(make_repo):
    repo = make_repo({
        "svc/app/main.py": "import occupancy_pb2_grpc\nimport helper_mod\nimport bridge.x\nimport pandas\n",
        "svc/app/__init__.py": "",
        "svc/helper_mod.py": "X = 1\n",
        "svc/bridge/x.py": "Y = 1\n",
        "proto/occupancy.proto": 'syntax = "proto3";\nservice Occ { rpc Get (A) returns (A); }\nmessage A {}\n',
        "pyproject.toml": '[project]\nname = "svc"\nversion = "0.1"\n',
    })
    assert unrecognised(structure.build(repo, "docs/viz-code")) == {"pandas"}


def test_airflow_zio_ignored_in_pack(tmp_path):
    st = stack.load(None)
    assert stack.covered(st, "python", "airflow.models") and stack.covered(st, "python", "flytekit")
    assert stack.covered(st, "scala", "zio.json")
    assert stack.sink_kinds(st, "scala", "zio.jdbc")[0]["kind"] == "sql-db"


def test_server_with_route_in_same_module_not_listed(make_repo):
    repo = make_repo({
        "pyproject.toml": '[project]\nname = "m"\nversion = "0.1"\n',
        "m/__init__.py": "",
        "m/a.py": "from fastapi import FastAPI\napp = FastAPI()\n\n\n@app.get('/x')\ndef x():\n    return 1\n",
        "m/b.py": "import flask\n",
    })
    assert structure.build(repo, "docs/viz-code")["stack"]["servers_without_routes"] == []


def test_pack_zero_match_not_flagged(make_repo):
    repo = make_repo({
        "build.sbt": 'lazy val s = (project in file("s"))\n',
        "s/src/main/scala/x/A.scala": "package x\nimport zio.http.*\n\nobject A\n",
    })
    s = structure.build(repo, "docs/viz-code")
    z = next(p for p in s["stack"]["patterns"] if p["name"] == "zio-http")
    assert z["matches"] == 0 and z["source"] == "pack"
    md = structure.summary_md(s)
    assert "- scala zio-http (pack): 0 routes in 0 files" in md
    assert "## Stack — 0 unrecognised imports, 1 server library without routes, 0 patterns with no match\n" in md
    assert stack.count(s["stack"]) == 1  # only the server library


ZIO_HTTP_REPO = {
    "build.sbt": 'lazy val common = (project in file("common"))\n',
    "common/src/main/scala/x/Server.scala": "package x\nimport zio.http.*\n\nobject Server\n",
}


def test_server_lib_cleared_by_stack_ignore(make_repo):
    repo = make_repo(ZIO_HTTP_REPO)
    s = structure.build(repo, "docs/viz-code")
    assert [x["prefix"] for x in s["stack"]["servers_without_routes"]] == ["zio.http"]   # the pack ignores zio only
    with_stack(repo, "scala:\n  ignore: [zio.http]\n")
    s = structure.build(repo, "docs/viz-code")
    assert s["stack"]["servers_without_routes"] == [] and stack.count(s["stack"]) == 0
    sinks = s["facts"]["common/src/main/scala/x/Server.scala"]["sinks"]
    assert [(x["kind"], x["lib"]) for x in sinks] == [("http", "zio.http")]


def test_pack_ignore_does_not_clear_server_lib():
    st = stack.load(None)
    assert stack.covered(st, "scala", "zio.http") and st.stack_ignore == {}


def test_whenless_pattern_with_import_less_first_file(make_repo):
    repo = make_repo({
        "pyproject.toml": '[project]\nname = "m"\nversion = "0.1"\n',
        "m/__init__.py": "",
        "m/a.py": "def x():\n    pass\n\n\nroute('/hello')\n",
    })
    with_stack(repo, "python:\n  routes:\n    - name: bare\n      path: literal\n      method: GET\n"
               "      regex: 'route[(]..(?P<path>[/\\w]+)'\n")
    p = subprocess.run([sys.executable, str(EXTRACT), str(repo)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    rep = json.loads((repo / "docs/viz-code/structure.json").read_text())["stack"]
    bare = next(x for x in rep["patterns"] if x["name"] == "bare")
    assert bare["matches"] == 1 and bare["first_file"] == "m/__init__.py"


FROM_IMPORTS = {
    "pyproject.toml": '[project]\nname = "loader"\nversion = "0.1"\n',
    "loader/warehouse.py": "from google.cloud import bigquery\n",
    "loader/bus.py": "from google.cloud import pubsub_v1\n",
    "loader/odd.py": "from xlib import y, z\nfrom flask import Flask\n",
}


def test_from_import_matched_by_name(make_repo):
    s = structure.build(make_repo(FROM_IMPORTS, name="loader"), "docs/viz-code")
    kinds = lambda f: {x["kind"] + ":" + x["lib"] for x in s["facts"][f]["sinks"]}
    assert kinds("loader/warehouse.py") == {"sql-db:google.cloud.bigquery"}
    assert kinds("loader/bus.py") == {"event:google.cloud.pubsub_v1"}
    assert kinds("loader/odd.py") == {"http-in:flask"}
    assert [(u["prefix"], u["files"]) for u in s["stack"]["unrecognised"]] == [("xlib", 1)]
    assert all("names" not in i for f in s["facts"].values() for i in f["imports"])


WHEN_FROM = {
    "pyproject.toml": '[project]\nname = "site"\nversion = "0.1"\n',
    "site/views.py": "from quart import views\n\n\n@app.route(\"/x\")\ndef x():\n    return 1\n",
    "site/other.py": "from quart import Quart\n\n\n@app.route(\"/y\")\ndef y():\n    return 1\n",
}


def test_when_matches_from_import_names(make_repo):
    repo = make_repo(WHEN_FROM, name="site")
    with_stack(repo, "python:\n  routes:\n    - name: quart-views\n      when: quart.views\n      path: literal\n"
                     "      method: GET\n      regex: '@\\w+\\.route\\(\"(?P<path>[^\"]*)'\n")
    s = structure.build(repo, "docs/viz-code")
    assert route_set(s, ".py") == {("GET", "/x", "site::site.views#x/0")}
    pat = next(p for p in s["stack"]["patterns"] if p["name"] == "quart-views")
    assert (pat["matches"], pat["files"], pat["first_file"]) == (1, 1, "site/views.py:1")
    assert stack.import_names([{"target": "quart", "relative": False, "names": ["views"]},
                               {"target": ".x", "relative": True, "names": ["y"]}]) == ["quart.views"]


def test_unrecognised_imports_leave_out_language_items_and_keep_the_repos_own_package(make_repo):
    """PHP global classes (`use Exception;`), a Rust `use` of a local enum's variants, a path alias from a tsconfig
    below the module root, and a library prefix that would also cover the repo's own package (`com.acme` when the
    repo is `com.acme.shop`): none is noise in the list, and a server-looking library is flagged first."""
    files = {"composer.json": "{\"name\": \"demo/app\"}\n",
             "app/Job.php": "<?php\n\nnamespace App;\n\nuse Exception;\nuse Closure;\nuse Monolog\\Logger;\n\n"
                            "class Job {}\n",
             "Cargo.toml": "[package]\nname = \"app\"\n",
             "src/main.rs": "use SortType::*;\nuse Self::Kind;\nuse dashmap::DashMap;\n\nenum SortType { A }\n",
             "package.json": "{\"name\": \"web\"}\n",
             "web/assets/tsconfig.json": "{\"compilerOptions\": {\"paths\": {\"@/*\": [\"./js/*\"]}}}\n",
             "web/assets/js/app.ts": "import { x } from '@/stores/x'\nimport { Hono } from 'hono'\nexport const y = x\n",
             "pom.xml": "<project/>\n",
             "src/main/java/com/acme/shop/App.java": "package com.acme.shop;\n\nimport com.acme.tools.Retry;\n\n"
                                                     "public class App {}\n"}
    s = structure.build(make_repo(files))
    got = [(u["lang"], u["prefix"], u.get("looks_like")) for u in s["stack"]["unrecognised"]]
    assert got == [("typescript", "hono", "server"), ("java", "com.acme.tools", None),
                   ("php", "Monolog", None), ("rust", "dashmap", None)]
    assert "- typescript `hono` — 1 file: web/assets/js/app.ts:2 (looks like a server library)" in structure.summary_md(s)


def test_a_long_summary_list_is_split_over_lines_with_its_label(make_repo):
    routes = "".join(f'@app.get("/r{i}")\ndef r{i}():\n    return 1\n\n' for i in range(30))
    files = {"app/__init__.py": "", "app/main.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n" + routes}
    md = structure.summary_md(structure.build(make_repo(files)))
    lines = [x for x in md.splitlines() if x.startswith("- **routes:**")]
    assert [x.count("; ") + 1 for x in lines] == [25, 5]


def test_a_decorator_route_recorded_on_its_function_is_no_route_looking_line(make_repo):
    """FastAPI records a route on the `def` below its decorators; the decorator line is matched through it."""
    src = ('from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n@router.get("/", response_model=list)\n'
           '@cache(\n    ttl=5,\n)\ndef read_items():\n    return []\n\n\n@router.post("/x")\nasync def create():\n'
           '    return 1\n')
    s = structure.build(make_repo({"app/__init__.py": "", "app/items.py": src}))
    assert len(s["facts"]["app/items.py"]["routes"]) == 2
    assert s["stack"]["routes_unmatched"] == []


def test_a_sqlmodel_table_class_with_no_tablename_is_entity_looking(make_repo):
    src = ("from sqlmodel import SQLModel, Field\n\n\nclass UserBase(SQLModel):\n    email: str\n\n\n"
           "class User(UserBase, table=True):\n    id: int\n\n\nclass UserCreate(UserBase):\n    password: str\n")
    s = structure.build(make_repo({"app/__init__.py": "", "app/models.py": src}))
    assert [(x["file"], x["classes"]) for x in s["stack"]["entities_without_table"]] == [("app/models.py", ["User"])]


def test_build_tool_configs_bundler_aliases_and_baseurl_imports_are_no_libraries(make_repo):
    """A build tool's config file imports its plugins, `$lib/x` is a bundler alias, and a bare import a tsconfig
    `baseUrl` resolves into the repo is the repo's own: none is an unrecognised library."""
    files = {"package.json": '{"name": "web"}\n',
             "webpack.config.js": "const Html = require('html-webpack-plugin')\nmodule.exports = { plugins: [new Html()] }\n",
             "tsconfig.json": '{"compilerOptions": {"baseUrl": "src"}}\n',
             "src/components/Button.ts": "export const Button = 1\n",
             "src/app.ts": "import { Button } from 'components/Button'\nimport { page } from '$app/stores'\n"
                           "import { x } from '$lib/x'\nimport Papa from 'papaparse'\nexport const y = [Button, page, x, Papa]\n"}
    s = structure.build(make_repo(files))
    assert [u["prefix"] for u in s["stack"]["unrecognised"]] == ["papaparse"]


def test_own_folders_imported_bare_are_not_libraries(make_repo):
    """tsconfig `"*"` paths, a folder of the module root a bundler resolves from (`src/x`), and a paths key mapped
    into node_modules (a library's own files, so the library stays a library)."""
    files = {"package.json": '{"name": "ui", "dependencies": {"pdfjs-dist": "4", "three": "1"}}\n',
             "tsconfig.json": '{"compilerOptions": {"paths": {"*": ["./web/src/*"], '
                              '"pdfjs-dist/types/src/*": ["./node_modules/pdfjs-dist/types/src/*"]}}}\n',
             "web/src/shop-lib/q.ts": "export const q = 1\n",
             "web/src/app.ts": "import { q } from 'shop-lib/q'\nimport { v } from 'src/views'\n"
                               "import * as e from 'pdfjs-dist/types/src/x'\nimport * as T from 'three'\n",
             "src/views.ts": "export const v = 2\n"}
    s = structure.build(make_repo(files))
    assert unrecognised(s) == {"pdfjs-dist", "three"}


def test_a_yaml_error_names_the_file_and_line(tmp_path):
    bad = write(tmp_path, "python:\n  imports:\n    - {prefix: x, kind: http\n")
    with pytest.raises(stack.StackError) as e:
        stack.load(bad)
    assert str(bad) in str(e.value) and "<unicode string>" not in str(e.value) and "line" in str(e.value)


def test_a_module_named_like_a_declared_library_does_not_hide_it(make_repo):
    """`app/celery.py` (the Celery app) beside a `celery` requirement: `import celery` elsewhere is the library."""
    files = {"requirements.txt": "celery==5.5\nasana>=3.0  # sdk\n", "app/__init__.py": "",
             "app/celery.py": "from celery import Celery\n\napp = Celery('app')\n",
             "app/importers/__init__.py": "", "app/importers/asana/__init__.py": "",
             "app/importers/asana/run.py": "import asana\n\n\ndef go():\n    return asana.Client()\n",
             "app/util.py": "def x():\n    return 1\n", "app/main.py": "import util\n"}
    s = structure.build(make_repo(files))
    assert {"celery", "asana"} <= unrecognised(s) and "util" not in unrecognised(s)
