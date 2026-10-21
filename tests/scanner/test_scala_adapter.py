from conftest import SHOP

from vizcode import ids
from vizcode.adapters import scala

SHOP_MOD = {"id": "mod:shop", "path": "shop", "lang": "scala", "build": "sbt"}


def by_id(res):
    return {n["id"]: n for n in res["nodes"]}


def test_scala_nodes():
    src = SHOP["shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala"].encode()
    res = scala.parse(src, "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala", SHOP_MOD, ids.IdRegistry())
    n = by_id(res)
    assert res["package"] == "io.demo.shop.repo"
    assert n["shop::io.demo.shop.repo.OrderRepo"]["parent"] == "shop::io.demo.shop.repo/"
    assert "shop::io.demo.shop.repo.OrderRepo#save/2" in n            # abstract declaration
    assert n["shop::io.demo.shop.repo.PgOrderRepo#load/2"]["visibility"] == "private"
    assert n["shop::io.demo.shop.repo.PgOrderRepo#load/2"]["signature"]["returns"] == "Option[String]"
    assert "shop::io.demo.shop.repo.PgOrderRepo$#live/0" in n          # companion object gets $
    # a class that is no case class is built from its class parameters
    pg = n["shop::io.demo.shop.repo.PgOrderRepo"]
    assert pg["ctor"] == {"params": [{"name": "table", "type": "String"}], "line": pg["line"]}
    top = n["shop::io.demo.shop.repo/OrderRepo.scala#helper/1"]
    assert n[top["parent"]]["kind"] == "file"


def test_scala_facts():
    src = SHOP["shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala"].encode()
    res = scala.parse(src, "shop/src/main/scala/io/demo/shop/repo/OrderRepo.scala", SHOP_MOD, ids.IdRegistry())
    assert [i["target"] for i in res["imports"]] == ["io.getquill", "io.demo.common.db"]
    texts = [s["text"] for s in res["strings"]]
    assert "INSERT INTO {table} (id, total) VALUES ({id}, {total})" in texts
    assert [e["key"] for e in res["env_keys"]] == ["ORDERS_TABLE"]


def test_scala_tapir_vals_collected():
    src = SHOP["shop/src/main/scala/io/demo/shop/api/BaseEndpoint.scala"].encode()
    res = scala.parse(src, "shop/src/main/scala/io/demo/shop/api/BaseEndpoint.scala", SHOP_MOD, ids.IdRegistry())
    assert set(res["tapir"]["vals"]) >= {"BaseEndpoint.base", "BaseEndpoint.V1.v1",
                                         "BaseEndpoint.V1.Orders.create", "BaseEndpoint.V1.Orders.byId"}


def test_scala_tapir_prefix_from_a_def_and_an_objects_apply():
    src = b"""package io.demo.api
import sttp.tapir.*
object BaseApi:
  private val base = endpoint.in("api")
  def v2 = base.in("v2")
  object V1:
    private val v1 = base.in("v1")
    def apply(): Endpoint[Unit, Unit, Unit, Unit, Any] = v1
  def all = repo.findAll
"""
    res = scala.parse(src, "shop/src/main/scala/io/demo/api/BaseApi.scala", SHOP_MOD, ids.IdRegistry())
    vals = res["tapir"]["vals"]
    assert {"BaseApi.v2", "BaseApi.V1"} <= set(vals)
    assert vals["BaseApi.V1"] == {"base": "v1", "segs": [], "scope": ["BaseApi", "V1"]}
    assert "io.demo.api.BaseApi$#all/0" in {n["id"].split("::")[1] for n in res["nodes"]}   # a plain def stays a method


# --- parking-city demo forms ------------------------------------------------
PC = {
    "build.sbt": 'lazy val common = (project in file("common"))\n'
                 'lazy val billing = (project in file("billing")).dependsOn(common)\n'
                 'lazy val pricing = (project in file("pricing")).dependsOn(common)\n'
                 'lazy val reservations = (project in file("reservations")).dependsOn(common)\n',
    "common/src/main/scala/city/parking/common/Config.scala":
        "package city.parking.common\n\nimport zio.*\n\nobject Config:\n\n"
        "  def env(key: String): Task[String] =\n    ZIO.attempt(sys.env(key))\n",
    "pricing/src/main/scala/city/parking/pricing/QuoteEndpoint.scala": '''package city.parking.pricing

import sttp.model.StatusCode
import sttp.tapir.*
import sttp.tapir.ztapir.*

object QuoteEndpoint:

  val quote =
    endpoint.get
      .in("v1" / "quote")
      .in(query[String]("zone"))
      .in(query[Int]("minutes"))
      .out(jsonBody[QuoteView])
      .errorOut(statusCode(StatusCode.NotFound).and(jsonBody[PricingError]))

  def routes(svc: PricingService): List[ZServerEndpoint[Any, Any]] =
    List(
      quote.zServerLogic((zone, minutes) =>
        svc.quote(zone, minutes).mapError(m => PricingError(m))
      )
    )
''',
    "billing/src/main/scala/city/parking/billing/SettleEndpoint.scala": '''package city.parking.billing

import sttp.tapir.*
import sttp.tapir.ztapir.*

object SettleEndpoint:

  val settle =
    endpoint.post
      .in("internal" / "settle")
      .out(jsonBody[SettleResult])
      .errorOut(stringBody)

  def routes(svc: BillingService): List[ZServerEndpoint[Any, Any]] =
    List(
      settle.zServerLogic(_ => svc.settle().mapBoth(_.getMessage, SettleResult(_)))
    )
''',
    "billing/src/main/scala/city/parking/billing/DeadLetters.scala": '''package city.parking.billing

import city.parking.common.EventProducer
import zio.*

trait DeadLetters:
  def park(key: String, value: String, reason: String): Task[Unit]

object DeadLetters:

  val Topic = "reservation-events.dlq"

  val live: ZLayer[EventProducer, Nothing, DeadLetters] =
    ZLayer.fromFunction: (producer: EventProducer) =>
      new DeadLetters:
        def park(key: String, value: String, reason: String): Task[Unit] =
          val escaped = reason.replace("\\"", "'")
          producer.publish(Topic, key, s"""{"reason":"$escaped","original":$value}""")
''',
    "billing/src/main/scala/city/parking/billing/Main.scala": '''package city.parking.billing

import zio.*
import zio.http.*

object Main extends ZIOAppDefault:

  private val http =
    ZIO.serviceWithZIO[BillingService]: svc =>
      Server.serve(ZioHttpInterpreter().toHttp(SettleEndpoint.routes(svc)))

  val run =
    (ReservationEventsConsumer.run.forkScoped *> http)
      .provide(
        Server.defaultWithPort(8080),
        DeadLetters.live
      )
''',
    "billing/src/main/scala/city/parking/billing/ReceiptStore.scala": '''package city.parking.billing

import zio.*

object ReceiptStore:

  def make(bucket: String): ZLayer[Any, Nothing, ReceiptStore] =
    ZLayer.succeed(new ReceiptStore { def put(invoice: Invoice, pdf: Array[Byte]): Task[String] = ZIO.succeed(bucket) })
''',
    "reservations/src/main/scala/city/parking/reservations/ReservationEndpoints.scala": '''package city.parking.reservations

import java.util.UUID
import sttp.model.StatusCode
import sttp.tapir.*
import sttp.tapir.ztapir.*

object ReservationEndpoints:

  private val base = endpoint.in("v1" / "reservations")

  private val errors = oneOf[ErrorBody](
    oneOfVariant(StatusCode.NotFound, jsonBody[ErrorBody])
  )

  val create =
    base.post
      .in(jsonBody[NewReservation])
      .out(statusCode(StatusCode.Created).and(jsonBody[Reservation]))
      .errorOut(errors)

  val get =
    base.get
      .in(path[UUID]("id"))
      .out(jsonBody[Reservation])
      .errorOut(errors)

  val cancel =
    base.post
      .in(path[UUID]("id") / "cancel")
      .out(jsonBody[Reservation])
      .errorOut(errors)

  def routes(svc: ReservationService): List[ZServerEndpoint[Any, Any]] =
    List(
      create.zServerLogic(r => svc.create(r).mapError(toBody)),
      get.zServerLogic(id => svc.find(id).mapError(toBody)),
      cancel.zServerLogic(id => svc.cancel(id).mapError(toBody))
    )
''',
}


def _parse(rel):
    mod = {"id": "mod:" + rel.split("/")[0], "path": rel.split("/")[0], "lang": "scala", "build": "sbt"}
    return scala.parse(PC[rel].encode(), rel, mod, ids.IdRegistry())


def test_tapir_routes_from_demo_endpoints(make_repo):
    from vizcode import structure
    s = structure.build(make_repo(PC))
    got = {(r["method"], r["path"]): r["handler"] for ff in s["facts"].values() for r in ff["routes"]}
    assert got == {
        ("GET", "/v1/quote"): "pricing::city.parking.pricing.QuoteEndpoint$#routes/1",
        ("POST", "/internal/settle"): "billing::city.parking.billing.SettleEndpoint$#routes/1",
        ("POST", "/v1/reservations"): "reservations::city.parking.reservations.ReservationEndpoints$#routes/1",
        ("GET", "/v1/reservations/{id}"): "reservations::city.parking.reservations.ReservationEndpoints$#routes/1",
        ("POST", "/v1/reservations/{id}/cancel"):
            "reservations::city.parking.reservations.ReservationEndpoints$#routes/1",
    }
    summary = structure.summary_md(s)
    assert "GET /v1/quote" in summary and "POST /v1/reservations/{id}/cancel" in summary


def test_behavioural_vals_are_methods_constants_are_not():
    n = by_id(_parse("billing/src/main/scala/city/parking/billing/Main.scala"))
    assert n["billing::city.parking.billing.Main$#run/0"]["signature"] == {"params": [], "returns": None}
    assert n["billing::city.parking.billing.Main$#http/0"]["visibility"] == "private"
    n = by_id(res := _parse("billing/src/main/scala/city/parking/billing/DeadLetters.scala"))
    assert n["billing::city.parking.billing.DeadLetters$#live/0"]["signature"]["returns"].startswith("ZLayer[")
    assert not any(i.endswith("#Topic/0") for i in n)                      # a string constant
    n = by_id(_parse("reservations/src/main/scala/city/parking/reservations/ReservationEndpoints.scala"))
    assert not any(i.endswith(("#base/0", "#errors/0", "#get/0")) for i in n)   # endpoint descriptions


def test_calls_inside_a_val_belong_to_it():
    res = _parse("billing/src/main/scala/city/parking/billing/Main.scala")
    ins = {c["callee"]: c["in"] for c in res["calls"]}
    assert ins["Server.serve"] == "billing::city.parking.billing.Main$#http/0"


def test_anonymous_implementations_get_named_classes():
    res = _parse("billing/src/main/scala/city/parking/billing/DeadLetters.scala")
    n = by_id(res)
    impl = n["billing::city.parking.billing.DeadLetters.live$impl"]
    assert impl["kind"] == "class" and impl["parent"] == "billing::city.parking.billing.DeadLetters$"
    park = n["billing::city.parking.billing.DeadLetters.live$impl#park/3"]
    assert park["parent"] == impl["id"]
    assert {c["callee"]: c["in"] for c in res["calls"]}["producer.publish"] == park["id"]
    # not assigned to a val: numbered within the owner
    n = by_id(_parse("billing/src/main/scala/city/parking/billing/ReceiptStore.scala"))
    assert "billing::city.parking.billing.ReceiptStore.$impl1#put/2" in n


def test_tapir_client_endpoint_is_not_a_route(make_repo):
    from vizcode import structure
    # scala-zio example message/.../client/notify/v1/SendNotification.scala
    src = '''package com.example.message.client.notify.v1

import sttp.client3.SttpBackend
import sttp.tapir.*
import sttp.tapir.client.sttp.SttpClientInterpreter

object SendNotification {
  private val sendEndpoint: PublicEndpoint[RequestBody, String, Response, Any] = endpoint.post
    .in("notifications").in(jsonBody[RequestBody]).out(jsonBody[Response]).errorOut(stringBody)

  def apply[R](backend: SttpBackend[Task, R], baseUri: Uri): Logic = {
    val toRequest = SttpClientInterpreter().toRequest(sendEndpoint, Some(baseUri))
    (body: RequestBody) => backend.send(toRequest(body))
  }
}
'''
    s = structure.build(make_repo({"build.sbt": 'lazy val message = project in file("message")\n',
                                   "message/src/main/scala/com/example/message/client/notify/v1/SendNotification.scala": src}))
    ff = next(iter(s["facts"].values()))
    assert ff["routes"] == []
    assert [(c["method"], c["path"], c["framework"]) for c in ff["clients"]] == [("POST", "/notifications", "tapir-client")]
    assert "POST /notifications" in structure.summary_md(s).split("clients")[1]


def test_behaviour_heuristic_edges():
    mod = {"id": "mod:m", "path": "m", "lang": "scala", "build": "sbt"}
    src = ('package p\n\nobject A:\n  val Note = "wrap it in ZIO.attempt"\n  val Max = 3\n'
           '  val f = (x: Int) => x + 1\n\nval top = new Runnable { def run() = () }\n')
    n = by_id(scala.parse(src.encode(), "m/src/main/scala/p/A.scala", mod, ids.IdRegistry()))
    assert "m::p.A$#f/0" in n
    assert not any(i.endswith(("#Note/0", "#Max/0")) for i in n)       # constants, even one mentioning ZIO.
    assert not any("$impl" in i for i in n)                            # top-level anonymous body: skipped on purpose


def test_tapir_handler_may_be_a_behavioural_val(make_repo):
    from vizcode import structure
    # scala-zio example common/.../HealthCheck.scala
    src = '''package com.example.common.http.api

import sttp.tapir.{PublicEndpoint, stringBody}
import sttp.tapir.ztapir.*
import zio.*

object HealthCheck {
  private val healthCheckEndpoint: PublicEndpoint[Unit, Unit, String, Any] = endpoint.in("health")
    .get.out(stringBody)

  val serverEndpoint: URLayer[HealthCheck, ZServerEndpoint[Any, Any]] =
    ZLayer { ZIO.service[HealthCheck].map(svc => healthCheckEndpoint.zServerLogic(svc)) }
}
'''
    s = structure.build(make_repo({"build.sbt": 'lazy val common = project in file("common")\n',
                                   "common/src/main/scala/com/example/common/http/api/HealthCheck.scala": src}))
    got = [(r["method"], r["path"], r["handler"]) for ff in s["facts"].values() for r in ff["routes"]]
    assert got == [("GET", "/health", "common::com.example.common.http.api.HealthCheck$#serverEndpoint/0")]


SPLIT_API = {
    "build.sbt": 'lazy val api = project in file("api")\n'
                 'lazy val shop = (project in file("shop")).dependsOn(api)\n',
    "api/src/main/scala/acme/api/Base.scala": '''package acme.api

import sttp.tapir.*

object Base:
  private val base = endpoint.in("shop")
  object V1:
    private val v1 = base.in("v1")
    val orders = v1.in("orders")
    val stock = v1.in("stock")
    val partner = v1.in("partner")
''',
    "api/src/main/scala/acme/api/CreateOrder.scala": '''package acme.api

import sttp.tapir.*
import sttp.tapir.json.zio.*

object CreateOrder:
  val endpoint = Base.V1.orders.post.in(jsonBody[In]).out(jsonBody[Out])
''',
    "api/src/main/scala/acme/api/CheckStock.scala": '''package acme.api

import sttp.tapir.*

object CheckStock:
  val endpoint = Base.V1.stock.get.in(query[String]("sku")).out(stringBody)
''',
    "api/src/main/scala/acme/api/PartnerQuote.scala": '''package acme.api

import sttp.tapir.*

object PartnerQuote:
  val endpoint = Base.V1.partner.post.out(stringBody)
''',
    "shop/src/main/scala/acme/shop/OrderServer.scala": '''package acme.shop

import acme.api.CreateOrder
import sttp.tapir.ztapir.*
import zio.*

object OrderServer:
  val serverEndpoint: URLayer[OrderSvc, ZServerEndpoint[Any, Any]] =
    ZLayer { ZIO.serviceWith[OrderSvc](CreateOrder.endpoint.zServerLogic) }
''',
    "shop/src/main/scala/acme/shop/Calls.scala": '''package acme.shop

import sttp.tapir.client.sttp.SttpClientInterpreter
import sttp.tapir.Endpoint

trait Calls:
  extension [I, E, O](e: Endpoint[Unit, I, E, O, Any])
    def call(uri: Uri) = SttpClientInterpreter().toRequest(e, Some(uri))
''',
    "shop/src/main/scala/acme/shop/StockClient.scala": '''package acme.shop

import acme.api.CheckStock
import sttp.client3.*

object StockClient extends Calls:
  def check(sku: String): Task[String] = backend.send(CheckStock.endpoint.call(uri)(sku)).map(_.body)
''',
}


def test_tapir_endpoint_bound_in_another_module_is_served_there(make_repo):
    from vizcode import structure
    s = structure.build(make_repo(SPLIT_API))
    got = [(r["method"], r["path"], r["handler"], f.rsplit("/", 1)[-1], r["line"])
           for f, ff in s["facts"].items() for r in ff["routes"]]
    assert got == [("POST", "/shop/v1/orders", "shop::acme.shop.OrderServer$#serverEndpoint/0", "OrderServer.scala", 9)]


def test_tapir_endpoint_only_called_is_a_client_and_a_bare_contract_is_neither(make_repo):
    from vizcode import structure
    s = structure.build(make_repo(SPLIT_API))
    clients = [(c["method"], c["path"]) for ff in s["facts"].values() for c in ff.get("clients", [])]
    assert clients == [("GET", "/shop/v1/stock")]                      # called through the client helper
    every = [r["path"] for ff in s["facts"].values() for r in ff["routes"]] + [p for _, p in clients]
    assert "/shop/v1/partner" not in every                              # described, never served or called here


def test_tapir_binding_follows_the_import_among_same_named_endpoints(make_repo):
    """v1 and v2 each define `object Quote` with a `def endpoint`; each server binds the one it imports."""
    from vizcode import structure
    files = {"build.sbt": 'lazy val api = project in file("api")\nlazy val shop = (project in file("shop")).dependsOn(api)\n'}
    for v in ("v1", "v2"):
        files[f"api/src/main/scala/acme/api/{v}/Quote.scala"] = (
            f'package acme.api.{v}\n\nimport sttp.tapir.*\n\nobject Quote:\n'
            f'  def endpoint = endpoint.in("quote" / "{v}").post.out(stringBody)\n')
        files[f"shop/src/main/scala/acme/shop/{v}/QuoteServer.scala"] = (
            f'package acme.shop.{v}\n\nimport acme.api.{v}.Quote\nimport sttp.tapir.ztapir.*\n\nobject QuoteServer:\n'
            f'  val serverEndpoint: URLayer[Svc, ZServerEndpoint[Any, Any]] =\n'
            f'    ZLayer {{ ZIO.serviceWith[Svc](Quote.endpoint.zServerLogic) }}\n')
    s = structure.build(make_repo(files))
    got = sorted((r["path"], r["handler"].split("::")[1]) for ff in s["facts"].values() for r in ff["routes"])
    assert got == [("/quote/v1", "acme.shop.v1.QuoteServer$#serverEndpoint/0"),
                   ("/quote/v2", "acme.shop.v2.QuoteServer$#serverEndpoint/0")]
