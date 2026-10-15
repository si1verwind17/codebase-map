import copy

from meaning_fixture import MEANING

from vizcode import calls, ids, mapcheck, structure
from vizcode.assemble import assemble


def test_calls_resolved_across_relative_import_and_library(shop_repo):
    cmap = assemble(structure.build(shop_repo, "docs/viz-code"), copy.deepcopy(MEANING))
    rels = {(r["from"], r["to"]): r for r in cmap["relations"] if r["kind"] == "calls"}
    fmt = "worker::worker.util.helpers#fmt/1"
    assert rels[("worker::worker.main#run/2", fmt)]["confidence"] == "confirmed"      # bare name, same service
    assert rels[("pylib::pylib.client#call/0", fmt)]["confidence"] == "confirmed"     # library → service it uses
    assert all(r["evidence"] for r in rels.values())


def test_calls_self_receiver_ambiguity_and_drop(make_repo):
    repo = make_repo({
        "app/__init__.py": "",
        "app/a.py": ("class A:\n    def go(self):\n        self.helper()\n        repo.save(1)\n        x.run()\n\n"
                     "    def helper(self):\n        pass\n\n\nclass B:\n    def helper(self):\n        pass\n"),
        "app/stores.py": ("class S1:\n    def save(self, v):\n        pass\n\n\nclass S2:\n    def save(self, v):\n        pass\n"),
        "app/runs.py": "".join(f"class R{i}:\n    def run(self):\n        pass\n\n\n" for i in range(4)),
    })
    s = structure.build(repo, "docs/viz-code")
    meaning = {"nodes": [{"id": "svc:app", "kind": "service", "name": "app", "modules": ["app"], "evidence": [{"file": "app/__init__.py", "line": 1}]}]}
    cmap = assemble(s, meaning)
    got = {(r["from"].split("::")[1], r["to"].split("::")[1]): r for r in cmap["relations"] if r["kind"] == "calls"}
    assert got[("app.a.A#go/0", "app.a.A#helper/0")]["confidence"] == "confirmed"   # self → same class, not B
    saves = [r for k, r in got.items() if k[1].endswith("#save/1")]
    assert len(saves) == 2 and all(r["confidence"] == "inferred" and r["why"] == "name matches 2 methods" for r in saves)
    assert not any(k[1].endswith("#run/0") for k in got)                          # 4 candidates: dropped
    assert any("match more than 3 methods" in p["text"] for p in cmap["problems"])
    assert mapcheck.check(cmap) == []


def test_calls_unique_name_with_unknown_receiver_is_inferred():
    nodes = [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
             {"id": "a::p/", "kind": "package", "name": "p", "parent": "svc:a"},
             {"id": "a::p.X", "kind": "class", "name": "X", "parent": "a::p/"},
             {"id": "a::p.X#m/0", "kind": "method", "name": "m", "parent": "a::p.X"},
             {"id": "a::p.Y", "kind": "class", "name": "Y", "parent": "a::p/"},
             {"id": "a::p.Y#target/0", "kind": "method", "name": "target", "parent": "a::p.Y"}]
    facts = {"p/x.py": {"calls": [{"callee": "other.target", "in": "a::p.X#m/0", "line": 3},
                                  {"callee": "Y.target", "in": "a::p.X#m/0", "line": 4}]}}
    rels, _ = calls.resolve(nodes, [], facts)
    assert len(rels) == 1 and rels[0]["confidence"] == "confirmed"   # `Y.target` names the owner
    rels, _ = calls.resolve(nodes, [], {"p/x.py": {"calls": [facts["p/x.py"]["calls"][0]]}})
    assert rels[0]["confidence"] == "inferred" and rels[0]["why"] == "matched by method name only"


def _two_classes():
    return [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
            {"id": "a::p/", "kind": "package", "name": "p", "parent": "svc:a"},
            {"id": "a::p.X", "kind": "class", "name": "X", "parent": "a::p/"},
            {"id": "a::p.X#m/0", "kind": "method", "name": "m", "parent": "a::p.X"},
            {"id": "a::p.X#save/0", "kind": "method", "name": "save", "parent": "a::p.X"},
            {"id": "a::p.Y", "kind": "class", "name": "Y", "parent": "a::p/"},
            {"id": "a::p.Y#fill/0", "kind": "method", "name": "fill", "parent": "a::p.Y"},
            {"id": "a::p.Y#save/0", "kind": "method", "name": "save", "parent": "a::p.Y"}]


def test_argument_and_string_text_is_not_a_callee():
    facts = {"p/x.py": {"calls": [{"callee": 'notifier.error(s"could not fill order")', "in": "a::p.X#m/0", "line": 3},
                                  {"callee": "ZIO.when(a.fill)", "in": "a::p.X#m/0", "line": 4}]}}
    rels, _ = calls.resolve(_two_classes(), [], facts)
    assert [r["to"] for r in rels] == []          # neither `error` nor `when` exists; `fill` is only an argument


def test_super_receiver_looks_outside_the_callers_own_class():
    facts = {"p/x.py": {"calls": [{"callee": "super().save", "in": "a::p.X#m/0", "line": 3}]}}
    rels, _ = calls.resolve(_two_classes(), [], facts)
    assert [r["to"] for r in rels] == ["a::p.Y#save/0"]


def test_a_literal_or_bracketed_receiver_is_never_trusted():
    for callee in ('", ".join(xs)', '"a b".split()', "{}.get(k)", "(a or b).save()"):
        assert calls.callee_parts(callee)[0] == "?", callee
    facts = {"p/x.py": {"calls": [{"callee": '"a b".save', "in": "a::p.X#m/0", "line": 3}]}}
    nodes = [n for n in _two_classes() if n["id"] != "a::p.X#save/0"]
    rels, _ = calls.resolve(nodes, [], facts)
    assert [r["confidence"] for r in rels] == ["inferred"]


def _sig(n):
    return {"params": [{"name": f"p{i}", "type": None} for i in range(n)], "returns": None}


def test_argument_count_narrows_same_named_methods():
    nodes = [n for n in _two_classes() if not n["id"].endswith("#save/0")] + [
        {"id": "a::p.X#save/1", "kind": "method", "name": "save", "parent": "a::p.X", "signature": _sig(1)},
        {"id": "a::p.Y#save/3", "kind": "method", "name": "save", "parent": "a::p.Y", "signature": _sig(3)}]
    facts = {"p/x.py": {"calls": [{"callee": "save", "args": 3, "in": "a::p.X#m/0", "line": 3},
                                  {"callee": "save", "args": 5, "in": "a::p.X#m/0", "line": 4}]}}
    rels, _ = calls.resolve(nodes, [], facts)
    by_line = {r["evidence"][0]["line"]: r["to"] for r in rels if len(r["evidence"]) == 1}
    targets = sorted({r["to"] for r in rels})
    assert "a::p.Y#save/3" in targets
    three = [r for r in rels if any(e["line"] == 3 for e in r["evidence"])]
    assert [r["to"] for r in three] == ["a::p.Y#save/3"]          # only save/3 takes three arguments
    five = [r for r in rels if any(e["line"] == 4 for e in r["evidence"])]
    assert sorted(r["to"] for r in five) == ["a::p.X#save/1", "a::p.Y#save/3"]   # none fits: keep both


def test_untrusted_receiver_with_no_fitting_arity_is_not_drawn():
    nodes = [n for n in _two_classes() if not n["id"].endswith("#save/0")] + [
        {"id": "a::p.Y#run/0", "kind": "method", "name": "run", "parent": "a::p.Y", "signature": _sig(0)}]
    def rels_for(callee):
        facts = {"p/x.py": {"calls": [{"callee": callee, "args": 1, "in": "a::p.X#m/0", "line": 3}]}}
        return [r["to"] for r in calls.resolve(nodes, [], facts)[0]]
    assert rels_for("stream.run") == []                  # a library value's `run(sink)`, not the repo's run/0
    assert rels_for("build(x).run") == []                # a chained result: same
    assert rels_for("Y.run") == ["a::p.Y#run/0"]         # the receiver names the owner: kept
    assert rels_for("run") == ["a::p.Y#run/0"]           # a bare name: kept


def test_a_scala_repeated_parameter_takes_any_count():
    nodes = [n for n in _two_classes() if not n["id"].endswith("#save/0")] + [
        {"id": "a::p.Y#update/2", "kind": "method", "name": "update", "parent": "a::p.Y",
         "signature": {"params": [{"name": "sql", "type": "String"}, {"name": "params", "type": "Any*"}],
                       "returns": None}}]
    facts = {"p/x.scala": {"calls": [{"callee": "db.update", "args": 4, "in": "a::p.X#m/0", "line": 3}]}}
    assert [r["to"] for r in calls.resolve(nodes, [], facts)[0]] == ["a::p.Y#update/2"]


def test_python_and_scala_call_sites_record_their_argument_count():
    from vizcode.adapters import python as py
    W = {"id": "mod:w", "path": "w", "lang": "python", "build": "python-package"}
    res = py.parse(b"def f():\n    g(1, 2, k=3)\n    h(*xs)\n", "w/a.py", W, ids.IdRegistry())
    args = {c["callee"]: c.get("args") for c in res["calls"]}
    assert args == {"g": 3, "h": None}
    from vizcode.adapters import scala as sc
    S = {"id": "mod:s", "path": "s", "lang": "scala", "build": "sbt"}
    res = sc.parse(b"package p\nobject O {\n  def f = g(1, 2)\n}\n", "s/O.scala", S, ids.IdRegistry())
    assert {c["callee"]: c.get("args") for c in res["calls"]}["g"] == 2
    res = sc.parse(b"package p\nobject O {\n  def f = db.transaction: c =>\n    c.go()\n}\n", "s/O.scala", S,
                   ids.IdRegistry())
    assert {c["callee"]: c.get("args") for c in res["calls"]}["db.transaction"] == 1   # a colon lambda is one argument


def test_super_dunder_calls_are_neither_drawn_nor_counted_as_dropped():
    nodes = [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
             {"id": "a::p/", "kind": "package", "name": "p", "parent": "svc:a"}]
    for c in "ABCDE":
        nodes += [{"id": f"a::p.{c}", "kind": "class", "name": c, "parent": "a::p/"},
                  {"id": f"a::p.{c}#__init__/0", "kind": "method", "name": "__init__", "parent": f"a::p.{c}"}]
    facts = {"p/x.py": {"calls": [{"callee": "super().__init__", "args": 0, "in": "a::p.A#__init__/0", "line": 3}]}}
    rels, problems = calls.resolve(nodes, [], facts)
    assert rels == [] and problems == []


def _copy_pasted(files=5):
    """A function defined in every workflow file, called from each file's own flow."""
    nodes = [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
             {"id": "a::wf/", "kind": "package", "name": "wf", "parent": "svc:a"}]
    facts = {}
    for i in range(files):
        f = f"wf/w{i}.py"
        nodes += [{"id": f"a::wf.w{i}", "kind": "file", "name": f"w{i}.py", "parent": "a::wf/", "file": f},
                  {"id": f"a::wf.w{i}#t1_read_check_point/0", "kind": "method", "name": "t1_read_check_point",
                   "parent": f"a::wf.w{i}", "file": f},
                  {"id": f"a::wf.w{i}#flow/0", "kind": "method", "name": "flow", "parent": f"a::wf.w{i}", "file": f}]
        facts[f] = {"calls": [{"callee": "t1_read_check_point", "args": 0, "in": f"a::wf.w{i}#flow/0", "line": 9}]}
    return nodes, facts


def test_a_colliding_name_resolves_to_the_callers_own_file():
    nodes, facts = _copy_pasted()
    rels, problems = calls.resolve(nodes, [], facts)
    assert sorted((r["from"], r["to"], r["confidence"]) for r in rels) == [
        (f"a::wf.w{i}#flow/0", f"a::wf.w{i}#t1_read_check_point/0", "confirmed") for i in range(5)]
    assert not any("not drawn" in p["text"] for p in problems)


def test_a_name_defined_in_many_files_is_reported_as_likely_copy_paste():
    nodes, facts = _copy_pasted()
    _, problems = calls.resolve(nodes, [], facts)
    smell = [p for p in problems if "copy-paste" in p["text"]]
    assert len(smell) == 1 and "`t1_read_check_point` ×5" in smell[0]["text"]   # one problem per module, not per name


def _service_and_repo():
    """OrderService.place delegates to OrderRepo.save; OrderService also has its own save in the same file."""
    f = "a/orders.py"
    return [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
            {"id": "a::p/", "kind": "package", "name": "p", "parent": "svc:a"},
            {"id": "a::p.orders", "kind": "file", "name": "orders.py", "parent": "a::p/", "file": f},
            {"id": "a::p.orders.OrderService", "kind": "class", "name": "OrderService", "parent": "a::p.orders", "file": f},
            {"id": "a::p.orders.OrderService#place/1", "kind": "method", "name": "place", "parent": "a::p.orders.OrderService", "file": f},
            {"id": "a::p.orders.OrderService#save/1", "kind": "method", "name": "save", "parent": "a::p.orders.OrderService", "file": f},
            {"id": "a::p.repo", "kind": "file", "name": "repo.py", "parent": "a::p/", "file": "a/repo.py"},
            {"id": "a::p.repo.OrderRepo", "kind": "class", "name": "OrderRepo", "parent": "a::p.repo", "file": "a/repo.py"},
            {"id": "a::p.repo.OrderRepo#save/1", "kind": "method", "name": "save", "parent": "a::p.repo.OrderRepo", "file": "a/repo.py"}]


def test_a_delegating_call_is_not_pulled_into_the_callers_own_file():
    for callee in ("self.repo.save", "OrderRepo.save", "repo.save"):
        facts = {"a/orders.py": {"calls": [{"callee": callee, "args": 1, "in": "a::p.orders.OrderService#place/1", "line": 5}]}}
        rels, _ = calls.resolve(_service_and_repo(), [], facts)
        targets = sorted(r["to"] for r in rels)
        assert "a::p.repo.OrderRepo#save/1" in targets, (callee, targets)
    facts = {"a/orders.py": {"calls": [{"callee": "OrderRepo.save", "args": 1, "in": "a::p.orders.OrderService#place/1", "line": 5}]}}
    rels, _ = calls.resolve(_service_and_repo(), [], facts)
    assert [(r["to"], r["confidence"]) for r in rels] == [("a::p.repo.OrderRepo#save/1", "confirmed")]   # the receiver names the owner


# --- a trait and its implementations are one call target -----------------------
# parking-city billing sources (demo forms: named and anonymous implementations of traits)
PC_BILLING = {
    'billing/src/main/scala/city/parking/billing/BillingService.scala': '''package city.parking.billing

import java.util.UUID
import zio.*

trait BillingService:
  def charge(ev: ReservationEvent): Task[Unit]
  def refund(ev: ReservationEvent): Task[Unit]
  def settle(): Task[Int]

object BillingService:

  val live: ZLayer[InvoiceRepo & StripeCharger & ReceiptStore, Nothing, BillingService] =
    ZLayer.fromFunction(Live(_, _, _))

  private final class Live(repo: InvoiceRepo, stripe: StripeCharger, receipts: ReceiptStore)
      extends BillingService:

    def charge(ev: ReservationEvent): Task[Unit] =
      val cents = ev.amountCents.getOrElse(0L)
      val inv   = Invoice(UUID.randomUUID(), ev.reservationId, ev.driverId, cents, "PAID")
      for
        _   <- stripe.confirm(ev.reservationId)
        pdf  = renderReceipt(inv)
        key <- receipts.put(inv, pdf)
        _   <- repo.insert(inv, Some(key))
      yield ()

    def refund(ev: ReservationEvent): Task[Unit] =
      stripe.refund(ev.reservationId) *> repo.markRefunded(ev.reservationId)

    /** Called by the nightly settlement DAG: marks every paid invoice settled
      * and returns how many were closed.
      */
    def settle(): Task[Int] =
      for
        open  <- repo.unsettled()
        count <- repo.markSettled(open.map(_.id))
      yield count

    private def renderReceipt(inv: Invoice): Array[Byte] =
      s"RECEIPT ${inv.id}\\nreservation ${inv.reservationId}\\ntotal ${inv.cents / 100.0}".getBytes("UTF-8")
''',
    'billing/src/main/scala/city/parking/billing/StripeCharger.scala': '''package city.parking.billing

import city.parking.common.Config
import com.stripe.Stripe
import com.stripe.model.{PaymentIntent, Refund}
import com.stripe.param.{PaymentIntentConfirmParams, RefundCreateParams}
import zio.*

/** Confirms or refunds Stripe payment intents (https://api.stripe.com). */
trait StripeCharger:
  def confirm(paymentIntentId: String): Task[Unit]
  def refund(paymentIntentId: String): Task[Unit]

object StripeCharger:

  val live: ZLayer[Any, Throwable, StripeCharger] =
    ZLayer:
      Config.env("STRIPE_API_KEY").map: key =>
        Stripe.apiKey = key
        new StripeCharger:
          def confirm(paymentIntentId: String): Task[Unit] =
            ZIO.attemptBlocking:
              PaymentIntent
                .retrieve(paymentIntentId)
                .confirm(PaymentIntentConfirmParams.builder().build())
              ()

          def refund(paymentIntentId: String): Task[Unit] =
            ZIO.attemptBlocking:
              Refund.create(RefundCreateParams.builder().setPaymentIntent(paymentIntentId).build())
              ()
''',
    'billing/src/main/scala/city/parking/billing/InvoiceRepo.scala': '''package city.parking.billing

import city.parking.common.Jdbc
import java.util.UUID
import zio.*

final case class Invoice(id: UUID, reservationId: String, driverId: String, cents: Long, status: String)

/** Owns the invoices table. */
trait InvoiceRepo:
  def insert(inv: Invoice, receiptKey: Option[String]): Task[Unit]
  def markRefunded(reservationId: String): Task[Unit]
  def unsettled(): Task[List[Invoice]]
  def markSettled(ids: List[UUID]): Task[Int]

object InvoiceRepo:

  val live: ZLayer[Jdbc, Nothing, InvoiceRepo] = ZLayer.fromFunction(Live(_))

  private final class Live(db: Jdbc) extends InvoiceRepo:

    def insert(inv: Invoice, receiptKey: Option[String]): Task[Unit] =
      db.update(
        """INSERT INTO invoices (id, reservation_id, driver_id, cents, status, receipt_key)
          |VALUES (?, ?, ?, ?, ?, ?)
          |ON CONFLICT (reservation_id) DO NOTHING""".stripMargin,
        inv.id, inv.reservationId, inv.driverId, inv.cents, inv.status, receiptKey.orNull
      ).unit

    def markRefunded(reservationId: String): Task[Unit] =
      db.update("UPDATE invoices SET status = 'REFUNDED' WHERE reservation_id = ?", reservationId).unit

    def unsettled(): Task[List[Invoice]] =
      db.query("SELECT id, reservation_id, driver_id, cents, status FROM invoices WHERE settled_at IS NULL AND status = 'PAID'"): rs =>
        Invoice(rs.getObject(1, classOf[UUID]), rs.getString(2), rs.getString(3), rs.getLong(4), rs.getString(5))

    def markSettled(ids: List[UUID]): Task[Int] =
      db.update(
        "UPDATE invoices SET settled_at = now() WHERE id = ANY (?)",
        ids.toArray
      )
''',
    'billing/src/main/scala/city/parking/billing/ReceiptStore.scala': '''package city.parking.billing

import city.parking.common.Config
import software.amazon.awssdk.core.sync.RequestBody
import software.amazon.awssdk.services.s3.S3Client
import software.amazon.awssdk.services.s3.model.PutObjectRequest
import zio.*

/** Stores receipt PDFs in the S3 bucket named by RECEIPTS_BUCKET. The nightly
  * export jobs write to the same bucket under the exports/ prefix.
  */
trait ReceiptStore:
  def put(invoice: Invoice, pdf: Array[Byte]): Task[String]

object ReceiptStore:

  val live: ZLayer[Any, Throwable, ReceiptStore] =
    ZLayer.scoped:
      for
        bucket <- Config.env("RECEIPTS_BUCKET")
        s3     <- ZIO.acquireRelease(ZIO.attempt(S3Client.create()))(c => ZIO.succeed(c.close()))
      yield new ReceiptStore:
        def put(invoice: Invoice, pdf: Array[Byte]): Task[String] =
          val key = s"receipts/${invoice.driverId}/${invoice.id}.pdf"
          ZIO
            .attemptBlocking:
              s3.putObject(
                PutObjectRequest.builder().bucket(bucket).key(key).contentType("application/pdf").build(),
                RequestBody.fromBytes(pdf)
              )
            .as(key)
''',
    'billing/src/main/scala/city/parking/billing/DeadLetters.scala': '''package city.parking.billing

import city.parking.common.EventProducer
import zio.*

/** Dead-letter parking for events billing could not process. The message is
  * wrapped with the failure reason and published to reservation-events.dlq;
  * an operator replays or discards it by hand.
  */
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
    'billing/src/main/scala/city/parking/billing/ReservationEventsConsumer.scala': '''package city.parking.billing

import city.parking.common.Config
import org.apache.kafka.clients.consumer.ConsumerRecord
import zio.*
import zio.json.*
import zio.kafka.consumer.*
import zio.kafka.serde.Serde

final case class ReservationEvent(
    `type`: String,
    reservationId: String,
    driverId: String,
    zoneId: Option[String],
    amountCents: Option[Long]
) derives JsonDecoder

/** Consumes the reservation-events topic as consumer group "billing".
  * Failures after retries are parked on reservation-events.dlq.
  */
object ReservationEventsConsumer:

  val Topic = "reservation-events"
  val Group = "billing"

  val run: ZIO[BillingService & DeadLetters, Throwable, Unit] =
    for
      brokers <- Config.kafkaBrokers
      billing <- ZIO.service[BillingService]
      dlq     <- ZIO.service[DeadLetters]
      settings = ConsumerSettings(brokers).withGroupId(Group)
      _ <- Consumer
             .plainStream(Subscription.topics(Topic), Serde.string, Serde.string)
             .mapZIO: record =>
               handle(billing, dlq, record.record).as(record.offset)
             .aggregateAsync(Consumer.offsetBatches)
             .mapZIO(_.commit)
             .runDrain
             .provide(Consumer.live, ZLayer.succeed(settings))
    yield ()

  private def handle(
      billing: BillingService,
      dlq: DeadLetters,
      rec: ConsumerRecord[String, String]
  ): UIO[Unit] =
    val attempt =
      for
        ev <- ZIO.fromEither(rec.value.fromJson[ReservationEvent]).mapError(new RuntimeException(_))
        _  <- ev.`type` match
                case "reservation.created"   => billing.charge(ev)
                case "reservation.cancelled" => billing.refund(ev)
                case _                       => ZIO.unit
      yield ()
    attempt
      .retry(Schedule.exponential(200.millis) && Schedule.recurs(3))
      .catchAll(err => dlq.park(rec.key, rec.value, err.getMessage).orDie)
''',
}

# scala-zio example forms: accessor methods on the companion next to the trait
ZIO_BILLING = {
    'billing/src/main/scala/com/example/billing/repo/InvoiceRepo.scala': '''package com.example.billing.repo

import com.example.billing.model.invoice.Invoice
import zio.{Ref, UIO, ULayer, URIO, ZIO, ZLayer}

// Shared outer dep: both areas read it, so it is provided once at the root
// (§4 outer). In-memory here; Postgres-shaped for a real swap.
trait InvoiceRepo {
  def insert(customer: String, amountCents: Long, issuedAt: java.time.Instant): UIO[Invoice]
  def get(id: Long): UIO[Option[Invoice]]
  def all: UIO[List[Invoice]]
}

object InvoiceRepo {
  def insert(
      customer: String,
      amountCents: Long,
      issuedAt: java.time.Instant
  ): URIO[InvoiceRepo, Invoice] = ZIO
    .serviceWithZIO[InvoiceRepo](_.insert(customer, amountCents, issuedAt))

  def get(id: Long): URIO[InvoiceRepo, Option[Invoice]] = ZIO.serviceWithZIO[InvoiceRepo](_.get(id))

  val all: URIO[InvoiceRepo, List[Invoice]] = ZIO.serviceWithZIO[InvoiceRepo](_.all)

  val live: ULayer[InvoiceRepo] = ZLayer {
    for {
      nextId <- Ref.make(1L)
      rows   <- Ref.make(Map.empty[Long, Invoice])
    } yield new InvoiceRepo {
      override def insert(
          customer: String,
          amountCents: Long,
          issuedAt: java.time.Instant
      ): UIO[Invoice] = for {
        id <- nextId.getAndUpdate(_ + 1)
        invoice = Invoice(id, customer, amountCents, issuedAt)
        _ <- rows.update(_ + (id -> invoice))
      } yield invoice

      override def get(id: Long): UIO[Option[Invoice]] = rows.get.map(_.get(id))

      override def all: UIO[List[Invoice]] = rows.get.map(_.values.toList.sortBy(_.id))
    }
  }
}
''',
    'billing/src/main/scala/com/example/billing/service/invoice/InvoiceService.scala': '''package com.example.billing.service.invoice

import com.example.billing.config.BillingConfig
import com.example.billing.model.invoice.{Invoice, InvoiceError}
import com.example.billing.repo.InvoiceRepo
import zio.{Clock, IO, URLayer, ZIO, ZLayer}

trait InvoiceService {
  def create(customer: String, amountCents: Long): IO[InvoiceError, Invoice]
  def get(id: Long): IO[InvoiceError, Invoice]
}

object InvoiceService {
  private type Env = InvoiceRepo & BillingConfig

  val live: URLayer[Env, InvoiceService] = ZLayer {
    for {
      repo   <- ZIO.service[InvoiceRepo]
      config <- ZIO.service[BillingConfig]
    } yield new InvoiceService {
      override def create(customer: String, amountCents: Long): IO[InvoiceError, Invoice] = for {
        _ <- ZIO.fail(InvoiceError.EmptyCustomer).when(customer.isBlank)
        _ <- ZIO.fail(InvoiceError.NonPositiveAmount)
          .when(amountCents <= 0 || amountCents > config.maxAmountCents)
        issuedAt <- Clock.instant
        invoice  <- repo.insert(customer.trim, amountCents, issuedAt)
      } yield invoice

      override def get(id: Long): IO[InvoiceError, Invoice] = repo.get(id)
        .someOrFail(InvoiceError.NotFound(id))
    }
  }
}
''',
}


def _resolve_scala(make_repo, sources: dict[str, str], files: list[str], build: str):
    repo = make_repo({"build.sbt": build, **{f: sources[f] for f in files}})
    s = structure.build(repo, "docs/viz-code")
    mods = {n["parent"] for n in s["nodes"] if n["kind"] == "package"}
    nodes = s["nodes"] + [{"id": m, "kind": "service", "name": m, "parent": None} for m in mods]
    rels, problems = calls.resolve(nodes, [], s["facts"])
    by_site: dict[tuple[str, int], list[dict]] = {}
    for r in rels:
        for e in r["evidence"]:
            by_site.setdefault((e["file"].rsplit("/", 1)[-1], e["line"]), []).append(r)
    return s, by_site, problems


def test_implements_recorded_on_named_and_anonymous_impls(make_repo):
    b = "billing/src/main/scala/city/parking/billing/"
    s, _, _ = _resolve_scala(make_repo, PC_BILLING, [b + "InvoiceRepo.scala", b + "StripeCharger.scala"],
                             'lazy val billing = project in file("billing")\n')
    n = {x["id"]: x for x in s["nodes"]}
    p = "billing::city.parking.billing."
    assert n[p + "InvoiceRepo.Live"]["implements"] == [p + "InvoiceRepo"]
    assert n[p + "StripeCharger.live$impl"]["implements"] == [p + "StripeCharger"]
    assert "implements" not in n[p + "InvoiceRepo$"]


def test_trait_and_impls_fold_into_one_candidate(make_repo):
    b = "billing/src/main/scala/city/parking/billing/"
    files = [b + f for f in ("BillingService.scala", "StripeCharger.scala", "InvoiceRepo.scala", "ReceiptStore.scala",
                             "DeadLetters.scala", "ReservationEventsConsumer.scala")]
    _, sites, problems = _resolve_scala(make_repo, PC_BILLING, files, 'lazy val billing = project in file("billing")\n')
    p = "billing::city.parking.billing."
    # stripe.confirm: a trait with one implementation → one edge, to the trait method
    assert [r["to"] for r in sites[("BillingService.scala", 23)]] == [p + "StripeCharger#confirm/1"]
    # billing.refund(ev): `billing: BillingService` is a typed parameter → that trait's method only, confirmed
    refund = sites[("ReservationEventsConsumer.scala", 52)]
    assert [(r["to"], r["confidence"]) for r in refund] == [(p + "BillingService#refund/1", "confirmed")]
    assert not any("match more than" in x["text"] for x in problems)


def test_scala_zio_accessor_call_drawn_again(make_repo):
    r = "billing/src/main/scala/com/example/billing/"
    files = [r + "repo/InvoiceRepo.scala", r + "service/invoice/InvoiceService.scala"]
    _, sites, problems = _resolve_scala(make_repo, ZIO_BILLING, files, 'lazy val billing = project in file("billing")\n')
    p = "billing::com.example.billing."
    assert sorted(x["to"] for x in sites[("InvoiceRepo.scala", 22)]) == \
        [p + "repo.InvoiceRepo#get/1", p + "service.invoice.InvoiceService#get/1"]
    assert not any("match more than" in x["text"] for x in problems)


DAG_CLASH = '''from airflow import DAG
from airflow.decorators import dag, task


def extract():
    return 1


def helper():
    return extract()


@dag(schedule=None)
def etl():
    @task
    def extract():
        return 2

    @task
    def load(x):
        return x

    load(extract())


@dag(schedule="@daily", dag_id="two")
def other():
    @task
    def load():
        return 3

    load()


with DAG("legacy", schedule_interval="@daily") as d:
    def helper(rows):
        return rows
'''


def test_qualified_nested_tasks_are_seen_only_inside_their_dag():
    from vizcode.adapters import python as py
    mod = {"id": "mod:jobs", "path": "jobs", "lang": "python", "build": "python-scripts"}
    res = py.parse(DAG_CLASH.encode(), "jobs/etl.py", mod, ids.IdRegistry())
    f = "jobs::jobs.etl"
    assert {f"{f}#etl.extract/0", f"{f}#etl.load/1", f"{f}#other.load/0", f"{f}#legacy.helper/1"} <= \
        {n["id"] for n in res["nodes"]}
    nodes = [{"id": "svc:jobs", "kind": "service", "parent": None, "name": "jobs"}] + \
        [dict(n, parent="svc:jobs") if n["kind"] == "file" else n for n in res["nodes"]]
    rels, _ = calls.resolve(nodes, [], {"jobs/etl.py": {"calls": res["calls"]}})
    got = {(r["from"].split("#")[1], r["to"].split("#")[1]): r["confidence"] for r in rels}
    # a top-level caller never sees a DAG's own `extract`
    assert got[("helper/0", "extract/0")] == "confirmed"
    assert ("helper/0", "etl.extract/0") not in got
    # inside the DAG its own task wins over the top-level function of the same name
    assert got[("etl/0", "etl.extract/0")] == "confirmed"
    assert ("etl/0", "extract/0") not in got
    # two DAGs with a `load` each: each DAG sees only its own
    assert got[("etl/0", "etl.load/1")] == "confirmed"
    assert got[("other/0", "other.load/0")] == "confirmed"
    assert ("other/0", "etl.load/1") not in got and ("etl/0", "other.load/0") not in got


# --- a capitalized receiver the scan does not define is a library type, not a call target -----
R = "reservations/src/main/scala/city/parking/reservations/"
PC_RESERVATIONS = {
    R + "ReservationService.scala": '''package city.parking.reservations

import zio.*

trait ReservationService:
  def create(req: NewReservation): Task[Reservation]

object ReservationService:

  private final class Live(pricing: PricingClient, cache: QuoteCache, stripe: StripeGateway)
      extends ReservationService:

    def create(req: NewReservation): Task[Reservation] =
      for
        cached <- cache.get(req.zoneId)
        quote  <- pricing.quote(req.zoneId, req.minutes)
        intent <- stripe.createIntent(req.id, quote.cents, quote.currency)
      yield Reservation(req.id, intent)
''',
    R + "QuoteCache.scala": '''package city.parking.reservations

import io.lettuce.core.RedisClient
import zio.*

trait QuoteCache:
  def get(key: String): Task[Option[Quote]]

object QuoteCache:

  val live: ZLayer[Any, Throwable, QuoteCache] =
    ZLayer.scoped:
      for
        cli <- ZIO.acquireRelease(ZIO.attempt(RedisClient.create(url)))(c => ZIO.succeed(c.shutdown()))
        con <- ZIO.attempt(cli.connect().sync())
      yield new QuoteCache:
        def get(key: String): Task[Option[Quote]] =
          ZIO.attemptBlocking(Option(con.get(s"quote:$key")))
''',
    R + "StripeGateway.scala": '''package city.parking.reservations

import com.stripe.model.PaymentIntent
import zio.*

trait StripeGateway:
  def createIntent(reservationId: String, cents: Long, currency: String): Task[String]

object StripeGateway:

  val live: ZLayer[Any, Throwable, StripeGateway] =
    ZLayer.succeed:
      new StripeGateway:
        def createIntent(reservationId: String, cents: Long, currency: String): Task[String] =
          ZIO.attemptBlocking:
            PaymentIntent.create(params).getId
''',
    R + "PricingClient.scala": '''package city.parking.reservations

import zio.*
import zio.http.*

trait PricingClient:
  def quote(zoneId: String, minutes: Int): Task[Quote]

object PricingClient:

  private final class Live(client: Client, base: String) extends PricingClient:
    def quote(zoneId: String, minutes: Int): Task[Quote] =
      ZIO.scoped:
        for
          resp <- client.request(Request.get(base))
          q    <- resp.body.asString.map(decode)
        yield q
''',
}


def test_unknown_capitalized_receiver_is_not_a_call(make_repo):
    _, sites, _ = _resolve_scala(make_repo, PC_RESERVATIONS, list(PC_RESERVATIONS),
                                 'lazy val reservations = project in file("reservations")\n')
    p = "reservations::city.parking.reservations."
    assert ("QuoteCache.scala", 14) not in sites          # RedisClient.create → not ReservationService#create
    assert ("StripeGateway.scala", 16) not in sites       # PaymentIntent.create → not ReservationService#create
    assert ("PricingClient.scala", 15) not in sites       # zio-http Request.get → not QuoteCache#get
    # the service's own calls still resolve, folded onto the trait methods
    assert [r["to"] for r in sites[("ReservationService.scala", 15)]] == [p + "QuoteCache#get/1"]
    assert [r["to"] for r in sites[("ReservationService.scala", 16)]] == [p + "PricingClient#quote/2"]
    assert [r["to"] for r in sites[("ReservationService.scala", 17)]] == [p + "StripeGateway#createIntent/3"]


def test_known_capitalized_receiver_still_resolves(make_repo):
    src = {R + "Quotes.scala": '''package city.parking.reservations

object Quotes:
  def get(key: String): String = key

class Pricing:
  def get(key: String): String = Quotes.get(key)
'''}
    _, sites, _ = _resolve_scala(make_repo, src, list(src), 'lazy val reservations = project in file("reservations")\n')
    assert [r["to"] for r in sites[("Quotes.scala", 7)]] == ["reservations::city.parking.reservations.Quotes$#get/1"]


def test_unknown_capitalized_receiver_is_skipped_with_one_candidate(make_repo):
    src = {R + "Cache.scala": '''package city.parking.reservations

import io.lettuce.core.RedisClient

class Sessions:
  def create(url: String): String = url

object Cache:
  def open(url: String): Unit = RedisClient.create(url)
'''}
    _, sites, _ = _resolve_scala(make_repo, src, list(src), 'lazy val reservations = project in file("reservations")\n')
    assert ("Cache.scala", 9) not in sites    # the only `create` in the scan is not RedisClient's


def _calls(make_repo, files: dict, modules: list[str]) -> dict:
    s = structure.build(make_repo(files), "docs/viz-code")
    first = next(iter(files))
    meaning = {"nodes": [{"id": "svc:app", "kind": "service", "name": "app", "modules": modules,
                          "evidence": [{"file": first, "line": 1}]}]}
    cmap = assemble(s, meaning)
    return {(r["from"].split("::")[1], r["to"].split("::")[1]): r for r in cmap["relations"] if r["kind"] == "calls"}


def test_a_parameter_typed_as_a_library_type_never_links_by_name(make_repo):
    got = _calls(make_repo, {
        "pom.xml": "<project><artifactId>app</artifactId></project>\n",
        "src/main/java/a/Api.java": "package a;\n\nimport java.util.Map;\n\npublic class Api {\n"
                                    "  public Object get(String id) { return id; }\n"
                                    "  public Object place(Map<String, Object> order) {\n"
                                    "    return order.get(\"id\");\n  }\n}\n",
        "src/main/java/a/Svc.java": "package a;\n\npublic class Svc {\n"
                                    "  public Object run(Repo repo) { return repo.load(\"x\"); }\n}\n",
        "src/main/java/a/Repo.java": "package a;\n\npublic class Repo {\n  public Object load(String k) { return k; }\n}\n",
        "src/main/java/a/Cache.java": "package a;\n\npublic class Cache {\n  public Object load(String k) { return k; }\n}\n",
    }, ["."])
    assert ("a.Api#place/1", "a.Api#get/1") not in got          # `order` is a java.util.Map
    assert got[("a.Svc#run/1", "a.Repo#load/1")]["confidence"] == "confirmed"   # `repo` is the repo's Repo
    assert ("a.Svc#run/1", "a.Cache#load/1") not in got


def test_a_wrapped_parameter_uses_its_outer_type(make_repo):
    got = _calls(make_repo, {
        "pyproject.toml": '[project]\nname = "app"\nversion = "0.1"\n',
        "app/__init__.py": "",
        "app/m.py": "from typing import Optional\n\n\nclass Order:\n    total: int\n\n    def get(self, k):\n        return k\n\n"
                    "    def save(self):\n        pass\n\n\n"
                    "def run(orders: list[Order], one: Optional[Order]) -> None:\n    orders.get(0)\n    one.save()\n",
    }, ["app"])
    assert ("app.m#run/2", "app.m.Order#get/1") not in got      # `orders` is a list
    assert ("app.m#run/2", "app.m.Order#save/0") in got         # Optional[Order] is an Order


def test_a_class_receiver_without_the_method_is_inherited_from_a_library(make_repo):
    got = _calls(make_repo, {
        "Gemfile": "gem \"rails\"\n",
        "app/models/book.rb": "class Book < ApplicationRecord\nend\n",
        "app/models/shelf.rb": "class Shelf < Base\n  def create\n  end\nend\n",
        "app/controllers/books_controller.rb": "class BooksController\n  def add\n    Book.create!(title: 1)\n"
                                                "    Shelf.create\n  end\nend\n",
        "app/controllers/members_controller.rb": "class MembersController\n  def create\n  end\nend\n",
    }, ["."])
    assert not any(k[0].endswith("#add/0") and k[1].endswith("MembersController#create/0") for k in got)
    assert any(k[0].endswith("#add/0") and k[1].endswith("Shelf#create/0") for k in got)


def test_wrapped_and_ambiguous_parameter_types_keep_their_calls(make_repo):
    got = _calls(make_repo, {
        "pyproject.toml": '[project]\nname = "app"\nversion = "0.1"\n',
        "app/__init__.py": "",
        "app/repo.py": "class Repo:\n    n: int\n\n    def save(self, v):\n        pass\n",
        "app/other.py": "class Repo:\n    m: int\n\n    def save(self, v):\n        pass\n",
        "app/api.py": "from typing import Annotated\n\n\n"
                      "def create(repo: Annotated[\"Repo\", 1]) -> None:\n    repo.save(1)\n\n\n"
                      "def maybe(repo: None | Repo) -> None:\n    repo.save(2)\n\n\n"
                      "def plain(d: dict) -> None:\n    d.save(3)\n",
    }, ["app"])
    assert any(k[0] == "app.api#create/1" and k[1].endswith("Repo#save/1") for k in got)   # Annotated unwraps
    assert any(k[0] == "app.api#maybe/1" and k[1].endswith("Repo#save/1") for k in got)    # None | Repo is a Repo
    assert not any(k[0] == "app.api#plain/1" for k in got)                                 # a dict is a library type


def test_a_rust_arc_dyn_parameter_keeps_its_call(make_repo):
    got = _calls(make_repo, {
        "Cargo.toml": "[package]\nname = \"app\"\nversion = \"0.1.0\"\n",
        "src/main.rs": "use std::sync::Arc;\n\npub trait Repo { fn save(&self, v: &str); }\n\npub struct Pg;\n"
                       "impl Repo for Pg { fn save(&self, v: &str) {} }\n\n"
                       "pub fn run(repo: Arc<dyn Repo>) { repo.save(\"x\"); }\n",
    }, ["."])
    assert any(k[0].endswith("#run/1") and "Repo#save/" in k[1] for k in got), got
