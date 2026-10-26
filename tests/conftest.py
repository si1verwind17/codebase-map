import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent          # the repo: skills/, viewer/, demo/, tests/
SCRIPTS = ROOT / "skills" / "visualizing-codebases" / "scripts"   # the skill's scanner, as installed
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "viewer" / "scripts"))   # guide_maps.py, a viewer build tool

os.environ["VIZ_AUDIT"] = "0"   # assemble.py's drawing audit spawns node; tests that want it unset this

GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}

SHOP = {
    "build.sbt": 'lazy val common = (project in file("common"))\n'
                 'lazy val shop = (project in file("shop")).dependsOn(common)\n',
    "docker-compose.yml": "services:\n  shop: {build: .}\n  worker: {build: .}\n",
    "common/src/main/scala/io/demo/common/db/Db.scala":
        "package io.demo.common.db\n\nobject Db {\n  def connect(url: String): Unit = ()\n}\n",
    "shop/src/main/scala/io/demo/shop/api/BaseEndpoint.scala":
        "package io.demo.shop.api\n\nimport sttp.tapir.*\n\nobject BaseEndpoint {\n"
        "  private val base = endpoint\n  object V1 {\n    private val v1 = base.in(\"v1\")\n"
        "    object Orders {\n      private val orders = v1.in(\"orders\")\n"
        "      val create = orders.in(\"create\")\n      val byId = orders\n    }\n  }\n}\n",
    "shop/src/main/scala/io/demo/shop/api/OrderApi.scala":
        "package io.demo.shop.api\n\nobject OrderApi {\n  def createEndpoint = {\n"
        "    BaseEndpoint.V1.Orders\n      .create\n      .post\n      .in(jsonBody[In])\n  }\n"
        "  def getEndpoint = BaseEndpoint.V1.Orders.byId.get.in(path[String](\"id\"))\n"
        "  def notRoute(m: Map[String, Int]) = m.get(\"x\")\n}\n",
    "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala":
        "package io.demo.shop.repo\n\nimport io.getquill.*\nimport io.demo.common.db.{Db, Pool}\n\n"
        "trait OrderRepo {\n  def save(id: String, total: BigDecimal): Unit\n}\n\n"
        "final class PgOrderRepo(table: String) extends OrderRepo {\n"
        "  def save(id: String, total: BigDecimal): Unit =\n"
        "    sql\"\"\"INSERT INTO #${table} (id, total) VALUES ($id, $total)\"\"\"\n"
        "  private def load(id: String)(using ctx: Ctx): Option[String] =\n"
        "    sql\"SELECT id FROM public.orders WHERE id = $id\"\n}\n\n"
        "object PgOrderRepo {\n  def live: PgOrderRepo = PgOrderRepo(sys.env(\"ORDERS_TABLE\"))\n}\n\n"
        "def helper(x: Int): Int = x\n",
    "worker/__init__.py": "",
    "worker/main.py":
        "import os\nimport requests\nfrom fastapi import APIRouter, FastAPI\nfrom .util.helpers import fmt\n\n"
        "BASE = os.getenv(\"SHOP_URL\", \"http://localhost:8080\")\n"
        "app = FastAPI()\nrouter = APIRouter(prefix=\"/v1/work\")\n\n\n"
        "@router.post(\"/run/{job_id}\")\ndef run(job_id: str, dry: bool = False) -> dict:\n"
        "    r = requests.post(f\"{BASE}/v1/orders/create\", json={\"job\": job_id})\n"
        "    return {\"ok\": fmt(r.status_code)}\n\n\n"
        "@app.get(\"/health\")\ndef health():\n    return \"ok\"\n\n\n"
        "class Job:\n    def __init__(self, name):\n        self.name = name\n\n"
        "    def store(self, conn, *args, **kw) -> None:\n"
        "        conn.execute(\"INSERT INTO public.jobs (name) \" \"VALUES (%s)\", (self.name,))\n"
        "        conn.execute(\"SELECT * FROM public.jobs j JOIN public.users u ON u.id = j.uid\")\n\n"
        "    def _secret(self):\n        \"\"\"Select the job from the queue.\"\"\"\n        return None\n\n\n"
        "def run(x):\n    return x\n",
    "worker/util/__init__.py": "",
    "worker/util/helpers.py": "def fmt(code: int) -> str:\n    return str(code)\n",
    "pylib/__init__.py": "",
    "pylib/client.py": "from worker.util.helpers import fmt\n\n\ndef call() -> str:\n    return fmt(1)\n",
    "scripts/run_once.py": "import psycopg\n\n\ndef main():\n    pass\n",
    "tests/test_x.py": "def test_x():\n    assert True\n",
    "docs/screen.py": "def ignored():\n    pass\n",
    "shop/src/test/scala/io/demo/shop/OrderSpec.scala": "package io.demo.shop\nclass OrderSpec\n",
}


# A Python service with a data type (a dataclass with fields) that a route handler takes and returns; the filler
# modules keep a one-file change under diff.py's full-rescan ratio.
TYPED = {
    "docker-compose.yml": "services:\n  orders: {build: .}\n",
    "orders/__init__.py": "",
    "orders/models.py": "from dataclasses import dataclass\n\n\n@dataclass\nclass Order:\n    id: str\n    total: float\n",
    "orders/main.py": ("from fastapi import FastAPI\n\nfrom .models import Order\n\napp = FastAPI()\n\n\n"
                       "@app.post(\"/orders\")\ndef create(order: Order) -> Order:\n    return order\n"),
    "orders/text.py": "def shout(s: str) -> str:\n    return s.upper()\n",
    "orders/clock.py": "def now() -> int:\n    return 0\n",
    "orders/ids.py": "def new_id() -> str:\n    return \"ord-1\"\n",
    "orders/money.py": "def cents(x: float) -> int:\n    return int(x * 100)\n",
}


QUART = {
    "pyproject.toml": '[project]\nname = "shopfront"\nversion = "0.1"\n',
    "shopfront/__init__.py":
        "from quart import Quart\n\napp = Quart(__name__)\n\n\n@app.get(\"/health\")\ndef health():\n    return \"ok\"\n",
    "shopfront/users.py":
        "from quart import Blueprint, jsonify\n\nbp = Blueprint(\"users\", __name__)\n\n\n"
        "@bp.route(\"/users/<int:id>\", methods=[\"GET\", \"DELETE\"])\ndef user(id):\n    return jsonify(id)\n\n\n"
        "@bp.route(\"/users\", methods=[\"POST\"])\ndef create_user():\n    return jsonify({})\n\n\n"
        "@bp.route(\"/users\")\ndef list_users():\n    return jsonify([])\n\n\ndef ping():\n    return \"pong\"\n",
    "shopfront/tasks.py":
        "from celery import Celery\nimport requests\n\ncelery = Celery(\"shopfront\")\n\n\n"
        "@celery.task\ndef send_welcome(user_id):\n    requests.post(\"https://mail.example.com/send\", json={\"u\": user_id})\n",
    "shopfront/schemas.py":
        "from marshmallow import Schema, fields\n\n\nclass UserSchema(Schema):\n    name = fields.Str()\n",
    "shopfront/wsgi.py":
        "from quart import current_app as app\nfrom shopfront.users import ping\n\napp.add_url_rule(\"/ping\", view_func=ping)\n",
}

QUART_STACK = (
    "# stack.yaml: written by the visualizing-codebases agent from this repo's code; read by extract.py.\n"
    "# Libraries and route styles the scanner does not know built in. Commit it; edit it by hand if a fact is wrong.\n"
    "python:\n"
    "  imports:\n"
    "    - {prefix: celery, kind: event}\n"
    "    - {prefix: quart, kind: http-in}\n"
    "  ignore: [marshmallow]\n"
    "  routes:\n"
    "    - name: quart\n"
    "      when: quart\n"
    "      path: literal\n"
    "      method: GET\n"
    "      regex: '@\\w+\\.route\\(\\s*[\"''](?P<path>[^\"'']*)[\"''](?:[^)]*methods\\s*=\\s*\\[(?P<methods>[^\\]]*)\\])?'\n"
    "    - name: quart-shortcut\n"
    "      when: quart\n"
    "      path: literal\n"
    "      regex: '@\\w+\\.(?P<method>get|post|put|delete|patch)\\(\\s*[\"''](?P<path>[^\"'']*)'\n"
    "    - name: quart-rule\n"
    "      when: quart\n"
    "      path: literal\n"
    "      method: GET\n"
    "      regex: 'add_url_rule\\(\\s*[\"''](?P<path>[^\"'']*)'\n"
)

HTTP4S = {
    "build.sbt": 'lazy val users = (project in file("users"))\n',
    "users/src/main/scala/acme/users/Routes.scala":
        "package acme.users\n\nimport org.http4s.*\nimport org.http4s.dsl.io.*\nimport cats.effect.IO\n\n"
        "class UserRoutes(repo: UserRepo) {\n"
        "  val routes: HttpRoutes[IO] = HttpRoutes.of[IO] {\n"
        "    case GET -> Root / \"users\" / IntVar(id) => repo.find(id).flatMap(_ => Ok(\"x\"))\n"
        "    case POST -> Root / \"users\" => Ok(\"created\")\n"
        "  }\n}\n",
    "users/src/main/scala/acme/users/UserRepo.scala":
        "package acme.users\n\nimport cats.effect.IO\nimport doobie.*\nimport doobie.implicits.*\n\n"
        "class UserRepo(xa: Transactor[IO]) {\n"
        "  val count: IO[Int] = sql\"select count(*) from users\".query[Int].unique.transact(xa)\n\n"
        "  def find(id: Int): IO[Option[User]] =\n"
        "    sql\"select id, name from users where id = $id\".query[User].option.transact(xa)\n}\n",
    "users/src/main/scala/acme/users/Main.scala":
        "package acme.users\n\nimport cats.effect.{IO, IOApp, Resource}\nimport org.http4s.ember.server.EmberServerBuilder\n"
        "import org.http4s.server.Server\n\n"
        "object Main extends IOApp.Simple {\n"
        "  val server: Resource[IO, Server] = EmberServerBuilder.default[IO].withHttpApp(null).build\n\n"
        "  def run: IO[Unit] = server.useForever\n}\n",
    "users/src/main/scala/acme/users/User.scala":
        "package acme.users\n\nimport io.circe.generic.semiauto.*\nimport io.circe.Codec\n\n"
        "case class User(id: Int, name: String)\n\nobject User {\n  given Codec[User] = deriveCodec\n}\n",
}

HTTP4S_STACK = (
    "# stack.yaml: written by the visualizing-codebases agent from this repo's code; read by extract.py.\n"
    "# Libraries and route styles the scanner does not know built in. Commit it; edit it by hand if a fact is wrong.\n"
    "scala:\n"
    "  effects: [IO, Resource, HttpRoutes]\n"
    "  ignore: [cats, io.circe]\n"
    "  routes:\n"
    "    - name: http4s\n"
    "      when: org.http4s\n"
    "      path: segments\n"
    "      regex: 'case\\s+(?P<method>GET|POST|PUT|DELETE|PATCH)\\s*->\\s*(?P<path>Root\\b[^=]*?)\\s*=>'\n"
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=GIT_ENV).stdout


def write_files(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def commit_all(repo: Path, message: str = "c") -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def make_repo(tmp_path):
    def _make(files: dict[str, str], name: str = "demo") -> Path:
        repo = tmp_path / name
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        write_files(repo, files)
        commit_all(repo, "init")
        return repo
    return _make


@pytest.fixture
def shop_repo(make_repo):
    return make_repo(SHOP)


@pytest.fixture
def typed_repo(make_repo):
    return make_repo(TYPED, name="orders-typed")


def with_stack(repo: Path, text: str, out_dir: str = "docs/viz-code") -> Path:
    """Write OUT/stack.yaml in the working tree (the scanner reads it from there; it need not be committed)."""
    p = repo / out_dir / "stack.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


@pytest.fixture
def quart_repo(make_repo):
    return make_repo(QUART, name="shopfront")


@pytest.fixture
def http4s_repo(make_repo):
    return make_repo(HTTP4S, name="users-service")


SPRING_BOOT = {
    "pom.xml": "<project><artifactId>shop</artifactId>\n  <modules>\n    <module>api</module>\n"
               "    <module>common</module>\n    <module>legacy</module>\n  </modules>\n</project>\n",
    "api/pom.xml": "<project><artifactId>shop-api</artifactId></project>\n",
    "common/pom.xml": "<project><artifactId>shop-common</artifactId></project>\n",
    "legacy/pom.xml": "<project><artifactId>shop-legacy</artifactId></project>\n",
    "api/src/main/java/io/demo/shop/api/OrderController.java":
        "package io.demo.shop.api;\n\n"
        "import io.demo.shop.common.Order;\n"
        "import io.demo.shop.common.OrderRepository;\n"
        "import org.springframework.web.bind.annotation.*;\n\n"
        "@RestController\n"
        "@RequestMapping(\"/v1/orders\")\n"
        "public class OrderController {\n"
        "  private final OrderRepository repo;\n\n"
        "  public OrderController(OrderRepository repo) { this.repo = repo; }\n\n"
        "  @GetMapping(\"/{id}\")\n"
        "  public Order get(@PathVariable Long id) { return repo.findById(id).orElseThrow(); }\n\n"
        "  @PostMapping\n"
        "  public Order create(@RequestBody Order order) { return repo.save(order); }\n\n"
        "  @RequestMapping(value = \"/{id}\", method = RequestMethod.DELETE)\n"
        "  public void delete(@PathVariable Long id) { repo.deleteById(id); }\n\n"
        "  public String lookup(java.util.Map<String, String> m) { return m.get(\"/not-a-route\"); }\n"
        "}\n",
    "api/src/main/java/io/demo/shop/api/PricingClient.java":
        "package io.demo.shop.api;\n\n"
        "import org.springframework.web.client.RestTemplate;\n\n"
        "public class PricingClient {\n"
        "  private final RestTemplate http = new RestTemplate();\n\n"
        "  public String quote(String sku) {\n"
        "    return http.getForObject(\"http://pricing:8080/v1/quotes/\" + sku, String.class);\n"
        "  }\n"
        "}\n",
    "api/src/main/java/io/demo/shop/api/OrderEvents.java":
        "package io.demo.shop.api;\n\n"
        "import org.springframework.kafka.annotation.KafkaListener;\n"
        "import org.springframework.stereotype.Component;\n\n"
        "@Component\n"
        "public class OrderEvents {\n"
        "  @KafkaListener(topics = \"orders\")\n"
        "  public void onOrder(String message) {}\n"
        "}\n",
    "common/src/main/java/io/demo/shop/common/Order.java":
        "package io.demo.shop.common;\n\n"
        "import jakarta.persistence.Entity;\n"
        "import jakarta.persistence.Id;\n"
        "import jakarta.persistence.Table;\n\n"
        "@Entity\n"
        "@Table(name = \"orders\", schema = \"shop\")\n"
        "public class Order {\n"
        "  @Id\n"
        "  private Long id;\n\n"
        "  public Long getId() { return id; }\n"
        "}\n",
    "common/src/main/java/io/demo/shop/common/OrderRepository.java":
        "package io.demo.shop.common;\n\n"
        "import org.springframework.data.jpa.repository.JpaRepository;\n\n"
        "public interface OrderRepository extends JpaRepository<Order, Long> {}\n",
    "legacy/src/main/java/io/demo/shop/legacy/StockResource.java":
        "package io.demo.shop.legacy;\n\n"
        "import jakarta.ws.rs.*;\n\n"
        "@Path(\"/legacy/stock\")\n"
        "public class StockResource {\n"
        "  @GET\n"
        "  public String list() { return \"[]\"; }\n\n"
        "  @GET\n"
        "  @Path(\"{sku}\")\n"
        "  public String one(@PathParam(\"sku\") String sku) { return sku; }\n\n"
        "  @Path(\"sub\")\n"
        "  public Object locator() { return null; }\n"
        "}\n",
    "legacy/src/main/java/io/demo/shop/legacy/BothResource.java":
        "package io.demo.shop.legacy;\n\n"
        "import jakarta.ws.rs.GET;\n"
        "import jakarta.ws.rs.Path;\n"
        "import org.springframework.web.bind.annotation.GetMapping;\n"
        "import org.springframework.web.bind.annotation.RequestMapping;\n\n"
        "@Path(\"/legacy/both\")\n"
        "@RequestMapping(\"/legacy/both\")\n"
        "public class BothResource {\n"
        "  @GET\n"
        "  @GetMapping\n"
        "  public String list() { return \"[]\"; }\n"
        "}\n",
}

KTOR = {
    "settings.gradle.kts": 'rootProject.name = "orders"\n',
    "build.gradle.kts": 'plugins { kotlin("jvm") version "2.0.0" }\n',
    "src/main/kotlin/io/demo/orders/Application.kt":
        "package io.demo.orders\n\n"
        "import io.ktor.client.HttpClient\n"
        "import io.ktor.client.request.get\n"
        "import io.ktor.server.application.*\n"
        "import io.ktor.server.response.*\n"
        "import io.ktor.server.routing.*\n\n"
        "fun Application.module() {\n"
        "    routing {\n"
        "        route(\"/v1\") {\n"
        "            get(\"/orders/{id}\") {\n"
        "                call.respond(OrderRepo.find(call.parameters[\"id\"]!!.toInt()))\n"
        "            }\n"
        "            post(\"/orders\") {\n"
        "                call.respondText(\"created\")\n"
        "            }\n"
        "        }\n"
        "        get(\"/health\") { call.respondText(\"ok\") }\n"
        "    }\n"
        "}\n\n"
        "suspend fun remote(client: HttpClient, m: Map<String, Int>): Int {\n"
        "    client.get(\"/remote\") { }\n"
        "    return m.get(\"/not-a-route\") ?: 0\n"
        "}\n",
    "src/main/kotlin/io/demo/orders/Orders.kt":
        "package io.demo.orders\n\n"
        "import org.jetbrains.exposed.sql.Table\n"
        "import org.jetbrains.exposed.sql.selectAll\n"
        "import org.jetbrains.exposed.sql.transactions.transaction\n\n"
        "object Orders : Table(\"orders\") {\n"
        "    val id = integer(\"id\")\n"
        "}\n\n"
        "object OrderRepo {\n"
        "    fun find(id: Int): String = transaction { Orders.selectAll().first().toString() }\n"
        "}\n",
}


NEST = {
    "package.json": '{"name": "shop", "private": true, "workspaces": ["apps/*", "libs/*"]}\n',
    "apps/api/package.json": '{"name": "@shop/api"}\n',
    "apps/api/src/main.ts":
        "import { NestFactory } from '@nestjs/core';\n"
        "import { AppModule } from './app.module';\n\n"
        "async function bootstrap() {\n"
        "  const app = await NestFactory.create(AppModule);\n"
        "  app.setGlobalPrefix('api');\n"
        "  await app.listen(3000);\n"
        "}\n"
        "bootstrap();\n",
    "apps/api/src/app.module.ts":
        "import { Module } from '@nestjs/common';\n"
        "import { ConfigModule } from '@nestjs/config';\n"
        "import { OrdersController } from './orders/orders.controller';\n\n"
        "@Module({ imports: [ConfigModule.forRoot()], controllers: [OrdersController] })\n"
        "export class AppModule {}\n",
    "apps/api/src/orders/orders.controller.ts":
        "import { All, Body, Controller, Get, Param, Post } from '@nestjs/common';\n"
        "import { OrdersService } from './orders.service';\n\n"
        "@Controller('orders')\n"
        "export class OrdersController {\n"
        "  constructor(private readonly orders: OrdersService) {}\n\n"
        "  @Get(':id')\n"
        "  findOne(@Param('id') id: string) {\n"
        "    return this.orders.find(id);\n"
        "  }\n\n"
        "  @Post()\n"
        "  create(@Body() body: unknown) {\n"
        "    return this.orders.create(body);\n"
        "  }\n\n"
        "  @All('legacy')\n"
        "  legacy() {\n"
        "    return this.orders.cache.get('legacy');\n"
        "  }\n"
        "}\n",
    "apps/api/src/orders/orders.service.ts":
        "import { Injectable } from '@nestjs/common';\n"
        "import { InjectRepository } from '@nestjs/typeorm';\n"
        "import { Repository } from 'typeorm';\n"
        "import { Order } from '@shop/db';\n"
        "import { PricingClient } from '../pricing/pricing.client';\n\n"
        "@Injectable()\n"
        "export class OrdersService {\n"
        "  readonly cache = new Map<string, string>();\n\n"
        "  constructor(@InjectRepository(Order) private readonly repo: Repository<Order>,\n"
        "              private readonly pricing: PricingClient) {}\n\n"
        "  find(id: string) {\n"
        "    return this.repo.findOneBy({ id: Number(id) });\n"
        "  }\n\n"
        "  async create(body: unknown) {\n"
        "    await this.pricing.quote('sku');\n"
        "    return this.repo.save(body as Order);\n"
        "  }\n"
        "}\n",
    "apps/api/src/pricing/pricing.client.ts":
        "import axios from 'axios';\n\n"
        "export class PricingClient {\n"
        "  async quote(sku: string): Promise<number> {\n"
        "    const r = await axios.get(`http://pricing:8080/v1/quotes/${sku}`);\n"
        "    return r.data.price;\n"
        "  }\n"
        "}\n",
    "libs/db/package.json": '{"name": "@shop/db"}\n',
    "libs/db/src/index.ts": "export { Order } from './order.entity';\n",
    "libs/db/src/order.entity.ts":
        "import { Column, Entity, PrimaryGeneratedColumn } from 'typeorm';\n\n"
        "@Entity('orders')\n"
        "export class Order {\n"
        "  @PrimaryGeneratedColumn()\n"
        "  id: number;\n\n"
        "  @Column()\n"
        "  total: number;\n"
        "}\n",
}

EXPRESS = {
    "package.json": '{"name": "orders-api"}\n',
    "src/app.js":
        "const express = require('express');\n"
        "const { listOrders, getOrder, auth } = require('./handlers');\n"
        "const v1 = require('./v1');\n\n"
        "const app = express();\n"
        "app.use(express.json());\n"
        "app.get('/orders', listOrders);\n"
        "app.get('/orders/:id', auth, getOrder);\n"
        "app.all('/ping', (req, res) => res.send('pong'));\n"
        "app.use('/v1', v1);\n\n"
        "const map = new Map();\n"
        "map.get('x');\n"
        "app.set('title', 'orders');\n"
        "app.get('title');\n"
        "app.listen(3000);\n",
    "src/handlers.js":
        "const { Pool } = require('pg');\n\n"
        "const pool = new Pool();\n\n"
        "async function listOrders(req, res) {\n"
        "  const r = await pool.query('SELECT id, total FROM orders');\n"
        "  res.json(r.rows);\n"
        "}\n\n"
        "async function getOrder(req, res) {\n"
        "  const r = await pool.query('SELECT id, total FROM orders WHERE id = $1', [req.params.id]);\n"
        "  res.json(r.rows[0]);\n"
        "}\n\n"
        "function auth(req, res, next) {\n"
        "  next();\n"
        "}\n\n"
        "module.exports = { listOrders, getOrder, auth };\n",
    "src/v1.js":
        "const express = require('express');\n\n"
        "const router = express.Router();\n"
        "router.post('/orders', createOrder);\n\n"
        "function createOrder(req, res) {\n"
        "  res.status(201).end();\n"
        "}\n\n"
        "module.exports = router;\n",
}


GO_SERVICE = {
    "go.mod": "module example.com/orders\n\ngo 1.22\n",
    "cmd/server/main.go":
        "package main\n\n"
        "import (\n"
        "\t\"log\"\n"
        "\t\"net/http\"\n\n"
        "\t\"example.com/orders/internal/orders\"\n"
        ")\n\n"
        "func main() {\n"
        "\th := orders.NewHandler(nil)\n"
        "\tmux := http.NewServeMux()\n"
        "\tmux.HandleFunc(\"GET /orders/{id}\", h.GetOrder)\n"
        "\tmux.HandleFunc(\"POST /orders\", h.CreateOrder)\n"
        "\tmux.HandleFunc(\"/healthz\", func(w http.ResponseWriter, r *http.Request) {})\n"
        "\tmux.Handle(\"/metrics\", http.HandlerFunc(metrics))\n"
        "\tlog.Fatal(http.ListenAndServe(\":8080\", mux))\n"
        "}\n\n"
        "func metrics(w http.ResponseWriter, r *http.Request) {}\n",
    "internal/orders/handler.go":
        "package orders\n\n"
        "import (\n"
        "\t\"context\"\n"
        "\t\"net/http\"\n\n"
        "\t\"github.com/jackc/pgx/v5/pgxpool\"\n"
        ")\n\n"
        "type Handler struct {\n"
        "\tdb *pgxpool.Pool\n"
        "}\n\n"
        "func NewHandler(db *pgxpool.Pool) *Handler { return &Handler{db: db} }\n\n"
        "func (h *Handler) GetOrder(w http.ResponseWriter, r *http.Request) {\n"
        "\ttotal, _ := h.load(r.Context(), r.PathValue(\"id\"))\n"
        "\tw.Write([]byte(total))\n"
        "}\n\n"
        "func (h *Handler) CreateOrder(w http.ResponseWriter, r *http.Request) {\n"
        "\tw.WriteHeader(http.StatusCreated)\n"
        "}\n\n"
        "func (h *Handler) load(ctx context.Context, id string) (string, error) {\n"
        "\tvar total string\n"
        "\terr := h.db.QueryRow(ctx, \"SELECT total FROM orders WHERE id = $1\", id).Scan(&total)\n"
        "\treturn total, err\n"
        "}\n",
    "internal/pricing/client.go":
        "package pricing\n\n"
        "import \"github.com/go-resty/resty/v2\"\n\n"
        "type Client struct {\n"
        "\thttp *resty.Client\n"
        "}\n\n"
        "func (c *Client) Quote(sku string) (string, error) {\n"
        "\tresp, err := c.http.R().Get(\"http://pricing:8080/v1/quotes/\" + sku)\n"
        "\treturn resp.String(), err\n"
        "}\n",
}

ASPNET_SERVICE = {
    "Shop/Shop.csproj": "<Project Sdk=\"Microsoft.NET.Sdk.Web\"></Project>\n",
    "Shop/Program.cs":
        "using Microsoft.AspNetCore.Builder;\n\n"
        "var builder = WebApplication.CreateBuilder(args);\n"
        "var app = builder.Build();\n"
        "app.MapGet(\"/ping\", () => \"pong\");\n"
        "app.Run();\n",
    "Shop/Controllers/OrdersController.cs":
        "using Microsoft.AspNetCore.Mvc;\n"
        "using Microsoft.Extensions.Logging;\n\n"
        "namespace Shop.Controllers;\n\n"
        "[ApiController]\n"
        "[Route(\"api/[controller]\")]\n"
        "public class OrdersController : ControllerBase\n"
        "{\n"
        "    [HttpGet(\"{id}\")]\n"
        "    public string Get(int id) => \"\";\n\n"
        "    [HttpPost]\n"
        "    public void Create() {}\n\n"
        "    [HttpGet(\"/health\")]\n"
        "    public string Health() => \"ok\";\n\n"
        "    [HttpDelete(\"~/admin/orders/{id}\")]\n"
        "    public void Purge(int id) {}\n"
        "}\n",
    "Shop/Data/ShopDb.cs":
        "using Microsoft.EntityFrameworkCore;\n\n"
        "namespace Shop.Data;\n\n"
        "public class ShopDb : DbContext\n"
        "{\n"
        "    protected override void OnModelCreating(ModelBuilder b)\n"
        "    {\n"
        "        b.Entity<Order>().ToTable(\"orders\");\n"
        "    }\n"
        "}\n",
}

AXUM_SERVICE = {
    "Cargo.toml": "[package]\nname = \"orders\"\nversion = \"0.1.0\"\n",
    "src/main.rs":
        "use axum::{routing::{get, post}, Router};\n\n"
        "mod handlers;\n\n"
        "fn app() -> Router {\n"
        "    Router::new()\n"
        "        .route(\"/orders/:id\", get(handlers::get_order))\n"
        "        .route(\"/orders\", post(create_order))\n"
        "        .nest(\"/admin\", admin())\n"
        "}\n\n"
        "async fn create_order() {}\n\n"
        "fn admin() -> Router {\n"
        "    Router::new()\n"
        "}\n",
    "src/handlers.rs":
        "use sqlx::PgPool;\n\n"
        "pub async fn get_order(pool: PgPool) {\n"
        "    sqlx::query(\"SELECT total FROM orders WHERE id = $1\").fetch_one(&pool).await;\n"
        "}\n",
}

SINATRA_SERVICE = {
    "Gemfile": "source \"https://rubygems.org\"\ngem \"sinatra\"\n",
    "app.rb":
        "require \"sinatra\"\n"
        "require \"pg\"\n\n"
        "DB = PG.connect(ENV[\"DATABASE_URL\"])\n\n"
        "get \"/orders/:id\" do\n"
        "  DB.exec_params(\"SELECT total FROM orders WHERE id = $1\", [params[:id]])\n"
        "end\n\n"
        "post '/orders' do\n"
        "  201\n"
        "end\n\n"
        "def helper\n"
        "  1\n"
        "end\n",
}

LARAVEL_SERVICE = {
    "composer.json": "{\"name\": \"demo/orders\"}\n",
    "routes/api.php":
        "<?php\n\n"
        "use App\\Http\\Controllers\\OrderController;\n"
        "use Illuminate\\Support\\Facades\\Route;\n\n"
        "Route::get('/orders/{id}', [OrderController::class, 'show']);\n"
        "Route::post('/orders', [OrderController::class, 'store']);\n"
        "Route::match(['get', 'post'], '/sync', fn () => 1);\n"
        "Route::prefix('v1')->group(function () {\n"
        "    Route::delete('/orders/{id}', [OrderController::class, 'destroy']);\n"
        "});\n",
    "app/Http/Controllers/OrderController.php":
        "<?php\n\n"
        "namespace App\\Http\\Controllers;\n\n"
        "use Illuminate\\Support\\Facades\\DB;\n\n"
        "class OrderController\n"
        "{\n"
        "    public function show($id)\n"
        "    {\n"
        "        return DB::select('SELECT total FROM orders WHERE id = ?', [$id]);\n"
        "    }\n\n"
        "    public function store() {}\n\n"
        "    public function destroy($id) {}\n"
        "}\n",
    "app/Models/Order.php":
        "<?php\n\n"
        "namespace App\\Models;\n\n"
        "use Illuminate\\Database\\Eloquent\\Model;\n\n"
        "class Order extends Model\n"
        "{\n"
        "    protected $table = 'orders';\n"
        "}\n",
}


@pytest.fixture
def go_repo(make_repo):
    return make_repo(GO_SERVICE, name="orders")


@pytest.fixture
def spring_repo(make_repo):
    return make_repo(SPRING_BOOT, name="shop")


@pytest.fixture
def ktor_repo(make_repo):
    return make_repo(KTOR, name="orders")


@pytest.fixture
def nest_repo(make_repo):
    return make_repo(NEST, name="shop")


@pytest.fixture
def express_repo(make_repo):
    return make_repo(EXPRESS, name="orders-api")


@pytest.fixture
def packs_without_patterns(monkeypatch, tmp_path):
    """The built-in packs minus their routes and tables groups: for tests of the stack.yaml mechanism that
    write their own patterns for frameworks a pack now covers."""
    import yaml
    from vizcode.scan import stack
    d = tmp_path / "packs"
    d.mkdir()
    for p in stack.PACKS.glob("*.yaml"):
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for groups in doc.values():
            for g in ("routes", "tables"):
                (groups or {}).pop(g, None)
        (d / p.name).write_text(yaml.safe_dump(doc), encoding="utf-8")
    monkeypatch.setattr(stack, "PACKS", d)
    monkeypatch.setattr(stack, "_DEFAULT", [])
    return d
