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


def test_a_literal_or_bracketed_receiver_is_never_trusted_and_a_literal_matches_nothing():
    for callee in ('", ".join(xs)', '"a b".split()', "{}.get(k)", "(a or b).save()"):
        assert calls.callee_parts(callee)[0] == "?", callee
    facts = {"p/x.py": {"calls": [{"callee": '"a b".save', "in": "a::p.X#m/0", "line": 3}]}}
    nodes = [n for n in _two_classes() if n["id"] != "a::p.X#save/0"]
    rels, _ = calls.resolve(nodes, [], facts)
    assert rels == []   # a string literal's method is the built-in type's, never a repo method


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


def test_a_call_passing_fewer_than_the_required_arguments_skips_the_method():
    """Python and Scala mark the parameters a call may leave out; other languages keep the upper bound alone."""
    def m(mid, lang, params):
        return {"id": mid, "kind": "method", "name": "save", "parent": mid.split("#")[0], "lang": lang,
                "signature": {"params": params, "returns": None}}
    req = {"name": "a", "type": None}
    opt = {"name": "b", "type": None, "optional": True}
    # the caller's own class has no `save`, so its lineage does not decide (it would: an implicit `this`)
    nodes = [n for n in _two_classes() if not n["id"].endswith("#save/0")] + [
        {"id": "a::p.W", "kind": "class", "name": "W", "parent": "a::p/"},
        m("a::p.W#save/1", "scala", [req]),
        m("a::p.Y#save/3", "scala", [req, req, req]),
        m("a::p.Y#save/2", "scala", [req, opt])]
    facts = {"p/x.scala": {"calls": [{"callee": "save", "args": 1, "in": "a::p.X#m/0", "line": 3}]}}
    assert sorted(r["to"] for r in calls.resolve(nodes, [], facts)[0]) == ["a::p.W#save/1", "a::p.Y#save/2"]
    for n in nodes:
        if n.get("lang"):
            n["lang"] = "kotlin"   # defaults not recorded: every method of up to its parameter count fits
    assert sorted(r["to"] for r in calls.resolve(nodes, [], facts)[0]) == [
        "a::p.W#save/1", "a::p.Y#save/2", "a::p.Y#save/3"]


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


def test_a_chained_result_matching_many_methods_is_not_counted_as_a_loss():
    nodes = [n for n in _two_classes() if "#save/" not in n["id"]]
    for c in "ABCD":
        nodes += [{"id": f"a::p.{c}", "kind": "class", "name": c, "parent": "a::p/"},
                  {"id": f"a::p.{c}#handle/1", "kind": "method", "name": "handle", "parent": f"a::p.{c}"}]
    def problems_for(callee):
        facts = {"p/x.py": {"calls": [{"callee": callee, "args": 1, "in": "a::p.X#m/0", "line": 3}]}}
        rels, problems = calls.resolve(nodes, [], facts)
        assert rels == []
        return [p["text"] for p in problems]
    assert problems_for("builder.route(x).handle") == []      # a library value's method: nothing was lost
    assert problems_for("()when.handle") == []                # a cut head: the same
    assert problems_for("handler.handle") == ["1 call site(s) in svc:a match more than 3 methods by name; not drawn"]


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


def test_python_and_scala_mark_the_parameters_a_call_may_leave_out():
    from vizcode.adapters import python as py, scala as sc
    W = {"id": "mod:w", "path": "w", "lang": "python", "build": "python-package"}
    res = py.parse(b"def f(a, b=1, *, c, d: int = 2):\n    pass\n", "w/a.py", W, ids.IdRegistry())
    sig = next(n for n in res["nodes"] if n["name"] == "f")["signature"]["params"]
    assert {p["name"]: p.get("optional", False) for p in sig} == {"a": False, "b": True, "c": False, "d": True}
    S = {"id": "mod:s", "path": "s", "lang": "scala", "build": "sbt"}
    src = (b"package p\nobject O {\n  def f[A](a: Int, b: Int = 1)(c: Int)(using d: D) = a\n  def g(implicit e: E) = 1\n"
           b"  def h[A](body: Int => A): A = ???\n}\n")
    res = sc.parse(src, "s/O.scala", S, ids.IdRegistry())
    by = {n["name"]: n["signature"]["params"] for n in res["nodes"] if n["kind"] == "method"}
    assert {p["name"]: p.get("optional", False) for p in by["f"]} == {"a": False, "b": True, "c": True, "d": True}
    assert [p.get("optional", False) for p in by["g"]] == [True]
    assert [p.get("optional", False) for p in by["h"]] == [False]   # type parameters are no parameter list


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


SIGNERS = {
    "sign/src/main/scala/acme/sign/SecretKey.scala": """package acme.sign

trait SecretKey:
  def sign(text: String): Task[String]

trait LocalKey extends SecretKey
trait VaultKey extends SecretKey

trait Chain[K <: SecretKey]:
  def get(ref: String): Task[K]

object LocalKey:
  def make(seed: String): Task[LocalKey] = ZIO.succeed(new LocalKey:
    def sign(text: String): Task[String] = ZIO.succeed(text))

object VaultKey:
  def make(path: String): Task[VaultKey] = ZIO.succeed(new VaultKey:
    def sign(text: String): Task[String] = ZIO.succeed(path))
""",
    "sign/src/main/scala/acme/sign/Signer.scala": """package acme.sign

trait Signer:
  def apply(ref: String, text: String): Task[String]

object LocalSigner:
  val live: URLayer[Chain[LocalKey], Signer] = ZLayer {
    ZIO.serviceWith[Chain[LocalKey]] { chain =>
      new Signer:
        def apply(ref: String, text: String): Task[String] =
          chain.get(ref).flatMap(key => key.sign(text))
    }
  }

object VaultSigner:
  val live: URLayer[Chain[VaultKey], Signer] = ZLayer {
    ZIO.serviceWith[Chain[VaultKey]] { chain =>
      new Signer:
        def apply(ref: String, text: String): Task[String] =
          chain.get(ref).flatMap(key => key.sign(text))
    }
  }

object AuditedSigner:
  val live: URLayer[Signer, Signer] = ZLayer {
    ZIO.serviceWith[Signer] { inner =>
      new Signer:
        def apply(ref: String, text: String): Task[String] = inner.apply(ref, text)
    }
  }

object AnySigner:
  def sign(key: SecretKey, text: String): Task[String] = key.sign(text)
  def signAll(keys: List[SecretKey], text: String): Task[String] = ZIO.foreach(keys)(k => k.sign(text)).map(_.head)
""",
}


def test_the_callers_declared_types_pick_the_implementation_it_holds(make_repo):
    """Two implementations of one interface: a caller whose layer is typed with one of them reaches that one only."""
    files = list(SIGNERS)
    _, sites, _ = _resolve_scala(make_repo, SIGNERS, files, 'lazy val sign = project in file("sign")\n')
    p = "sign::acme.sign."
    local, vault = ([r for r in sites[("Signer.scala", n)] if r["to"].endswith("#sign/1")] for n in (11, 20))
    assert [r["to"] for r in local] == [p + "LocalKey.$impl1#sign/1"]
    assert [r["to"] for r in vault] == [p + "VaultKey.$impl1#sign/1"]
    assert local[0]["confidence"] == "inferred" and local[0]["why"] == "narrowed by the caller's declared types"
    # a caller whose types name only the shared interface: nothing to narrow by, every candidate stays
    # a layer that builds a Signer around another: Signer is what it is, so its type narrows nothing
    assert all(r.get("why") != "narrowed by the caller's declared types" for r in sites.get(("Signer.scala", 28), []))
    assert len(sites[("Signer.scala", 33)]) == 1 and sites[("Signer.scala", 33)][0]["to"] == p + "SecretKey#sign/1"
    # `List[SecretKey]`: the two implementations sit two levels below SecretKey (through LocalKey and VaultKey,
    # which do not declare sign) and fold into its method, as for one level
    assert [r["to"] for r in sites[("Signer.scala", 34)]] == [p + "SecretKey#sign/1"]


def test_scala_zio_accessor_call_drawn_again(make_repo):
    r = "billing/src/main/scala/com/example/billing/"
    files = [r + "repo/InvoiceRepo.scala", r + "service/invoice/InvoiceService.scala"]
    _, sites, problems = _resolve_scala(make_repo, ZIO_BILLING, files, 'lazy val billing = project in file("billing")\n')
    p = "billing::com.example.billing."
    # `ZIO.serviceWithZIO[InvoiceRepo](_.get(id))` in a def typed `URIO[InvoiceRepo, ..]`: the repo's get, not the
    # service's same-named one
    assert [(x["to"], x["why"]) for x in sites[("InvoiceRepo.scala", 22)]] == \
        [(p + "repo.InvoiceRepo#get/1", "narrowed by the caller's declared types")]
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


def test_an_implementation_two_levels_down_folds_into_the_interface_method():
    # Repo declares save; Base implements Repo without declaring it; PgRepo extends Base and declares it
    nodes = [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
             {"id": "a::p/", "kind": "package", "name": "p", "parent": "svc:a"},
             {"id": "a::p.Repo", "kind": "class", "name": "Repo", "parent": "a::p/"},
             {"id": "a::p.Repo#save/1", "kind": "method", "name": "save", "parent": "a::p.Repo"},
             {"id": "a::p.Base", "kind": "class", "name": "Base", "parent": "a::p/", "implements": ["a::p.Repo"]},
             {"id": "a::p.Base#close/0", "kind": "method", "name": "close", "parent": "a::p.Base"},
             {"id": "a::p.PgRepo", "kind": "class", "name": "PgRepo", "parent": "a::p/", "implements": ["a::p.Base"]},
             {"id": "a::p.PgRepo#save/1", "kind": "method", "name": "save", "parent": "a::p.PgRepo"},
             {"id": "a::p.Api", "kind": "class", "name": "Api", "parent": "a::p/"},
             {"id": "a::p.Api#post/1", "kind": "method", "name": "post", "parent": "a::p.Api",
              "signature": {"params": [{"name": "repo", "type": "Repo", "refs": ["a::p.Repo"]}]}}]
    by_id = {n["id"]: n for n in nodes}
    assert calls._abstractions(by_id) == {"a::p.PgRepo#save/1": "a::p.Repo#save/1"}
    rels, _ = calls.resolve(nodes, [], {"p/api.x": {"calls": [{"callee": "repo.save", "in": "a::p.Api#post/1",
                                                                "line": 3, "args": 1}]}})
    assert [(r["to"], r["confidence"]) for r in rels] == [("a::p.Repo#save/1", "confirmed")]


def test_python_subclass_implements_its_repo_base(make_repo):
    repo = make_repo({
        "app/__init__.py": "",
        "app/repo.py": "from abc import ABC, abstractmethod\n\n\nclass OrderRepo(ABC):\n    @abstractmethod\n"
                       "    def save(self, order):\n        ...\n\n\nclass PgOrderRepo(OrderRepo):\n"
                       "    def save(self, order):\n        return order\n",
        "app/api.py": "from app.repo import OrderRepo\n\n\ndef place(repo: OrderRepo, order):\n    repo.save(order)\n",
    })
    s = structure.build(repo, "docs/viz-code")
    n = {x["id"]: x for x in s["nodes"]}
    assert n["app::app.repo.PgOrderRepo"]["implements"] == ["app::app.repo.OrderRepo"]
    assert "implements" not in n["app::app.repo.OrderRepo"]      # ABC is the library's
    meaning = {"nodes": [{"id": "svc:app", "kind": "service", "name": "app", "modules": ["app"],
                          "evidence": [{"file": "app/__init__.py", "line": 1}]}]}
    cmap = assemble(s, meaning)
    assert [(r["to"], r["confidence"]) for r in cmap["relations"] if r["kind"] == "calls"] == \
        [("app::app.repo.OrderRepo#save/1", "confirmed")]


def test_a_call_on_a_field_typed_with_a_repo_class_reaches_that_class():
    # `repo.save(o)` and `this.repo.find(id)` on a field `OrderRepository repo`: that interface's methods, not
    # another class's same-named one; a field of a library type adds nothing
    nodes = [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
             {"id": "a::p/", "kind": "package", "name": "p", "parent": "svc:a"},
             {"id": "a::p.OrderRepository", "kind": "class", "name": "OrderRepository", "parent": "a::p/"},
             {"id": "a::p.OrderRepository#save/1", "kind": "method", "name": "save", "parent": "a::p.OrderRepository"},
             {"id": "a::p.OrderRepository#find/1", "kind": "method", "name": "find", "parent": "a::p.OrderRepository"},
             {"id": "a::p.AuditLog", "kind": "class", "name": "AuditLog", "parent": "a::p/"},
             {"id": "a::p.AuditLog#save/1", "kind": "method", "name": "save", "parent": "a::p.AuditLog"},
             {"id": "a::p.OrderService", "kind": "class", "name": "OrderService", "parent": "a::p/",
              "fields": [{"name": "repo", "type": "OrderRepository"}, {"name": "names", "type": "List<String>"}]},
             {"id": "a::p.OrderService#place/1", "kind": "method", "name": "place", "parent": "a::p.OrderService"}]
    site = [{"callee": "repo.save", "in": "a::p.OrderService#place/1", "line": 3, "args": 1},
            {"callee": "this.repo.find", "in": "a::p.OrderService#place/1", "line": 4, "args": 1}]
    rels, _ = calls.resolve(nodes, [], {"p/s.java": {"calls": site}})
    assert sorted((r["to"], r["confidence"]) for r in rels) == [("a::p.OrderRepository#find/1", "confirmed"),
                                                               ("a::p.OrderRepository#save/1", "confirmed")]


def _classes(*specs):
    """A service of classes: (name, [methods], [repo classes it extends], lang)."""
    nodes = [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
             {"id": "a::p/", "kind": "package", "name": "p", "parent": "svc:a"}]
    for name, methods, supers, lang in specs:
        nodes.append({"id": f"a::p.{name}", "kind": "class", "name": name, "parent": "a::p/", "lang": lang,
                      "implements": [f"a::p.{s}" for s in supers]})
        nodes += [{"id": f"a::p.{name}#{m}/0", "kind": "method", "name": m, "parent": f"a::p.{name}"} for m in methods]
    return nodes


def _targets(nodes, *calls_in):
    facts = {"p/x": {"calls": [{"callee": callee, "in": f"a::p.{caller}/0", "line": i + 1}
                               for i, (caller, callee) in enumerate(calls_in)]}}
    rels, _ = calls.resolve(nodes, [], facts)
    return sorted((r["from"].removeprefix("a::p."), r["to"].removeprefix("a::p.")) for r in rels)


def test_a_self_call_reaches_only_the_callers_own_lineage():
    """`$this->authorize()` inherited from a framework base is no call to an unrelated class's `authorize`; a base
    class calling a method only its subclass defines (a template method) still reaches the subclass."""
    nodes = _classes(("Controller", [], [], "php"), ("SongController", ["show"], ["Controller"], "php"),
                     ("SongRequest", ["authorize"], [], "php"), ("UserRequest", ["authorize"], [], "php"),
                     ("Job", ["run"], [], "php"), ("ImportJob", ["handle"], ["Job"], "php"),
                     ("Audits", ["audit"], [], "php"), ("Base", ["go"], ["Audits"], "php"))
    assert _targets(nodes, ("SongController#show", "$this->authorize"), ("Job#run", "$this->handle"),
                    ("Base#go", "$this->audit")) == [
        ("Base#go/0", "Audits#audit/0"), ("Job#run/0", "ImportJob#handle/0")]


def test_go_ruby_and_rust_keep_methods_a_value_may_embed_include_or_deref_to():
    nodes = _classes(("Server", ["serve"], [], "go"), ("Logger", ["log"], [], "go"), ("Post", [], [], "rust"),
                     ("Wrapper", ["inner"], [], "rust"))
    assert _targets(nodes, ("Server#serve", "self.log"), ("Server#serve", "post.inner")) == [
        ("Server#serve/0", "Logger#log/0"), ("Server#serve/0", "Wrapper#inner/0")]


def test_an_object_method_on_an_unknown_value_is_no_call():
    nodes = _classes(("Rates", ["current"], [], "java"), ("ItemMetric", ["equals", "toString"], [], "java"))
    assert _targets(nodes, ("Rates#current", "container.getDate().equals"),
                    ("Rates#current", "UUID.randomUUID().toString"), ("Rates#current", "other.toString")) == []
    assert _targets(nodes, ("ItemMetric#equals", "this.toString")) == [("ItemMetric#equals/0", "ItemMetric#toString/0")]


def test_a_value_named_after_a_repo_class_is_that_class():
    nodes = _classes(("UserModel", ["find"], [], "scala"), ("ApiKeyModel", ["insert"], [], "scala"),
                     ("EmailModel", ["insert"], [], "scala"), ("UserService", ["register"], [], "scala"))
    assert _targets(nodes, ("UserService#register", "userModel.insert"), ("UserService#register", "userModel.find"),
                    ("UserService#register", "emailRepo.insert")) == [
        ("UserService#register/0", "EmailModel#insert/0"), ("UserService#register/0", "UserModel#find/0")]


def test_a_value_named_after_a_class_of_another_service_names_nothing():
    """`downloadService.fromAlbum` in the web app is no call into the server's class DownloadService."""
    nodes = _classes(("Page", ["show"], [], "typescript"), ("Exports", ["fromAlbum"], [], "typescript")) + [
        {"id": "svc:b", "kind": "service", "name": "b", "parent": None},
        {"id": "b::q.DownloadService", "kind": "class", "name": "DownloadService", "parent": "svc:b", "lang": "php"}]
    assert _targets(nodes, ("Page#show", "downloadService.fromAlbum")) == [("Page#show/0", "Exports#fromAlbum/0")]


def test_a_repo_method_named_like_an_object_method_is_still_reached():
    nodes = _classes(("Money", ["valueOf"], [], "java"), ("PasswordHasher", ["hash"], [], "java"),
                     ("Signup", ["run"], [], "java"))
    assert _targets(nodes, ("Signup#run", "Money.valueOf"), ("Signup#run", "passwordHasher.hash")) == [
        ("Signup#run/0", "Money#valueOf/0"), ("Signup#run/0", "PasswordHasher#hash/0")]
    assert _targets(nodes, ("Signup#run", "hasher.hash")) == [("Signup#run/0", "PasswordHasher#hash/0")]


def test_a_value_named_after_a_class_still_reaches_extensions_and_module_functions():
    """Kotlin `fun User.toDto()` at top level, C# `static ToDto(this Order o)`, a Python module `config`."""
    nodes = _classes(("User", [], [], "kotlin"), ("Order", [], [], "csharp"), ("Config", [], [], "python"),
                     ("OrderExtensions", [], [], "csharp"), ("Page", ["show"], [], "kotlin")) + [
        {"id": "a::p/UserMappers.kt", "kind": "file", "name": "UserMappers.kt", "parent": "a::p/"},
        {"id": "a::p/UserMappers.kt#toDto/0", "kind": "method", "name": "toDto", "parent": "a::p/UserMappers.kt"},
        {"id": "a::p/config.py", "kind": "file", "name": "config.py", "parent": "a::p/"},
        {"id": "a::p/config.py#load/0", "kind": "method", "name": "load", "parent": "a::p/config.py"},
        {"id": "a::p.OrderExtensions#ToDto/1", "kind": "method", "name": "ToDto", "parent": "a::p.OrderExtensions",
         "signature": {"params": [{"name": "o", "type": "this Order"}], "returns": None}}]
    got = _targets(nodes, ("Page#show", "user.toDto"), ("Page#show", "config.load"), ("Page#show", "order.ToDto"))
    assert [t for _, t in got] == ["OrderExtensions#ToDto/1", "a::p/UserMappers.kt#toDto/0", "a::p/config.py#load/0"]


def test_a_self_call_reaches_a_sibling_base_of_a_subclass_and_an_outer_class():
    """A mixin's `self.save()` is the model's that the class using the mixin extends; Java `Outer.this.refresh()`
    is the outer class's."""
    nodes = _classes(("TimestampMixin", ["touch"], [], "python"), ("Model", ["save"], [], "python"),
                     ("Order", [], ["TimestampMixin", "Model"], "python"), ("Other", ["save"], [], "python"),
                     ("Outer", ["refresh"], [], "java"), ("Inner", ["go"], [], "java"),
                     ("Cache", ["refresh"], [], "java"))
    assert _targets(nodes, ("TimestampMixin#touch", "self.save"), ("Inner#go", "Outer.this.refresh")) == [
        ("Inner#go/0", "Outer#refresh/0"), ("TimestampMixin#touch/0", "Model#save/0")]


def test_a_self_call_never_reaches_a_sibling_under_a_shared_base():
    """`self.get_credentials()` in a hook whose bases define none is no call to another hook extending the same
    base: the lineage is the class, its bases, the classes extending it and their bases, whatever the order."""
    nodes = _classes(("BaseHook", ["log"], [], "python"), ("AwsHook", ["get_credentials"], ["BaseHook"], "python"),
                     ("GcpBase", ["project"], ["BaseHook"], "python"),
                     ("GkeHook", ["get_conn"], ["GcpBase", "BaseHook"], "python"),
                     ("GcsHook", ["get_credentials"], ["GcpBase"], "python"))
    assert _targets(nodes, ("GkeHook#get_conn", "self.get_credentials")) == []


def test_a_self_call_reaches_the_other_part_of_a_split_class_and_a_scala_self_type():
    """C# `partial class Foo` in two files is two nodes (`Foo`, `Foo~2`) of one class; a Scala trait's self-type
    (`self: Repo =>`) is not in its header."""
    nodes = _classes(("Foo", ["Go"], [], "csharp"), ("Audit", ["log"], [], "scala"), ("Repo", ["save"], [], "scala"))
    nodes += [{"id": "a::p.Foo~2", "kind": "class", "name": "Foo", "parent": "a::p/", "lang": "csharp"},
              {"id": "a::p.Foo~2#Helper/0", "kind": "method", "name": "Helper", "parent": "a::p.Foo~2"}]
    assert _targets(nodes, ("Foo#Go", "this.Helper"), ("Audit#log", "self.save")) == [
        ("Audit#log/0", "Repo#save/0"), ("Foo#Go/0", "Foo~2#Helper/0")]


def test_a_bare_call_reaches_no_class_method_where_the_language_has_no_implicit_this():
    """PHP `trim($s)`, Python `helper()`: a bare call is a free function (or a built-in), never another class's
    method; Java's implicit `this` still reaches the caller's own method."""
    nodes = _classes(("Twig", ["render"], [], "php"), ("Transformer", ["trim"], [], "php"),
                     ("Svc", ["go", "helper"], [], "java"), ("Other", ["helper"], [], "java"))
    nodes += [{"id": "a::p/util.php", "kind": "file", "name": "util.php", "parent": "a::p/"},
              {"id": "a::p/util.php#slug/0", "kind": "method", "name": "slug", "parent": "a::p/util.php"}]
    assert _targets(nodes, ("Twig#render", "trim"), ("Twig#render", "slug"), ("Svc#go", "helper")) == [
        ("Svc#go/0", "Svc#helper/0"), ("Twig#render/0", "a::p/util.php#slug/0")]


def test_a_literal_receiver_or_an_unknown_attribute_of_a_class_reaches_no_repo_method():
    nodes = _classes(("Check", ["save"], [], "python"), ("Curl", ["get"], [], "python"), ("Matrix", ["join"], [], "python"),
                     ("Views", ["index"], [], "python"))
    assert _targets(nodes, ("Views#index", '"\\n".join'), ("Views#index", "Check.objects.get")) == []


def test_a_value_named_like_the_tail_of_one_class_picks_it():
    """`resource.getUrl` with `UmsResource#getUrl` and `SmsHomeAdvertise#getUrl`: the UmsResource one."""
    nodes = _classes(("UmsResource", ["getUrl"], [], "java"), ("SmsHomeAdvertise", ["getUrl"], [], "java"),
                     ("Config", ["load"], [], "java"))
    assert _targets(nodes, ("Config#load", "resource.getUrl")) == [("Config#load/0", "UmsResource#getUrl/0")]


def test_a_singleton_chain_a_rust_module_function_and_a_generic_value_name():
    """`Database.getInstance().query()` is no attribute chain; a Rust `mod`'s function is bare-callable; a value
    named `list` picks no class by its name's tail (`PagedList`)."""
    nodes = _classes(("Database", ["getInstance", "query"], [], "java"), ("Other", ["query"], [], "java"),
                     ("Svc", ["run"], [], "java"), ("util", ["helper", "work"], [], "rust"),
                     ("PagedList", ["get"], [], "java"), ("Cache", ["get"], [], "java"))
    assert ("Svc#run/0", "Database#query/0") in _targets(nodes, ("Svc#run", "Database.getInstance().query"))
    assert _targets(nodes, ("util#work", "helper")) == [("util#work/0", "util#helper/0")]
    assert sorted(t for _, t in _targets(nodes, ("Svc#run", "list.get"))) == ["Cache#get/0", "PagedList#get/0"]


def test_a_values_method_never_reaches_a_free_function_of_that_name(make_repo):
    # `row.get(k)` is the value's own method; `store.get(k)` goes through a module the file imports
    got = _calls(make_repo, {
        "app/__init__.py": "",
        "app/store.py": "def get(key):\n    return key\n",
        "app/api.py": "from app import store\n\n\ndef read(row):\n    return row.get(\"a\")\n\n\n"
                      "def load():\n    return store.get(\"b\")\n",
        "src/lib.rs": "pub fn get(k: &str) -> u8 { 0 }\n\npub fn run(m: &Map) -> u8 { m.get(\"a\") }\n\n"
                      "pub fn via() -> u8 { crate::get(\"b\") }\n",
        "Cargo.toml": "[package]\nname = \"app\"\nversion = \"0.1.0\"\n",
    }, ["."])
    assert any(k[0].endswith("#load/0") and k[1].endswith("#get/1") for k in got), got
    assert not any(k[0].endswith("#read/1") for k in got), got
    assert any(k[0].endswith("#via/0") and k[1].endswith("#get/1") for k in got), got
    assert not any(k[0].endswith("#run/1") for k in got), got


def test_a_field_type_matches_classes_of_the_callers_language_only():
    # a Python model's `options = Column(...)`: a TypeScript class named Column elsewhere is not its type
    nodes = [{"id": "svc:a", "kind": "service", "name": "a", "parent": None},
             {"id": "a::m", "kind": "file", "name": "m", "parent": "svc:a", "lang": "python"},
             {"id": "a::m.Source", "kind": "class", "name": "Source", "parent": "a::m", "lang": "python",
              "fields": [{"name": "options", "type": "Column"}]},
             {"id": "a::m.Source#to_dict/0", "kind": "method", "name": "to_dict", "parent": "a::m.Source", "lang": "python"},
             {"id": "a::c", "kind": "file", "name": "c", "parent": "svc:a", "lang": "python"},
             {"id": "a::c.Container", "kind": "class", "name": "Container", "parent": "a::c", "lang": "python"},
             {"id": "a::c.Container#set_schema/1", "kind": "method", "name": "set_schema", "parent": "a::c.Container",
              "lang": "python"},
             {"id": "a::ui", "kind": "file", "name": "ui", "parent": "svc:a", "lang": "typescript"},
             {"id": "a::ui.Column", "kind": "class", "name": "Column", "parent": "a::ui", "lang": "typescript"},
             {"id": "a::ui.Column#render/0", "kind": "method", "name": "render", "parent": "a::ui.Column",
              "lang": "typescript"}]
    rels, _ = calls.resolve(nodes, [], {"m.py": {"calls": [{"callee": "self.options.set_schema",
                                                            "in": "a::m.Source#to_dict/0", "line": 3, "args": 1}]}})
    assert [r["to"] for r in rels] == ["a::c.Container#set_schema/1"]


def test_a_go_package_named_unlike_its_folder_and_a_common_name_on_a_value(make_repo):
    # `store.Fetch` through `.../userstore` (`package store`) keeps its call; `seen.add()` on a set, a name five
    # methods share, is not drawn to the two class methods left once the free functions drop out
    got = _calls(make_repo, {
        "go.mod": "module github.com/acme/app\n\ngo 1.21\n",
        "internal/userstore/store.go": "package store\n\nfunc Fetch(id string) string {\n\treturn id\n}\n",
        "api/api.go": "package api\n\nimport \"github.com/acme/app/internal/userstore\"\n\n"
                      "func Handle() string {\n\treturn store.Fetch(\"x\")\n}\n",
        "app/__init__.py": "",
        "app/a.py": "def add(r, c):\n    return 1\n", "app/b.py": "def add(r, c):\n    return 2\n",
        "app/c.py": "def add(r, c):\n    return 3\n",
        "app/k.py": "class Fields:\n    def add(self, r):\n        return 1\n\n\nclass Recorder:\n"
                    "    def add(self, r, c):\n        return 2\n",
        "app/use.py": "def run(items, recorder):\n    seen = set()\n    for i in items:\n        seen.add(i, 1)\n"
                      "        recorder.add(i, 1)\n        seen.add(i)\n",
        "app/fill.py": "class Filler:\n    def add(self, r, c):\n        return 0\n\n    def fill(self, items):\n"
                       "        seen = set()\n        for i in items:\n            seen.add(i, 1)\n",
        "app/users.py": "class User:\n    def add(self, r, c):\n        return 1\n\n\nclass AdminUser:\n"
                        "    def add(self, r, c):\n        return 2\n\n\nclass InMemoryListState:\n"
                        "    def add(self, r, c):\n        return 3\n",
        "app/who.py": "def who(user, admin_user, list_state, s):\n    user.add(1, 2)\n    admin_user.add(1, 2)\n"
                      "    list_state.add(1, 2)\n    s.add(1, 2)\n",
    }, ["."])
    # a name naming a class exactly wins over one ending in it; whole words end a name; one letter is no name
    assert sorted(k[1].rsplit(".", 1)[-1] for k in got if k[0].endswith("#who/4")) == [
        "AdminUser#add/2", "InMemoryListState#add/2", "User#add/2"], got
    # no guess by arity or by elimination of the caller's own class
    assert not any(k[0].endswith("#fill/1") for k in got), got
    assert any(k[0].endswith("#Handle/0") and k[1].endswith("#Fetch/1") for k in got), got
    # the value named after a class still narrows to it
    assert [k[1].rsplit(".", 1)[-1] for k in got if k[0].endswith("#run/2")] == ["Recorder#add/2"], got


def test_a_common_name_with_no_free_function_still_narrows_by_its_receiver(make_repo):
    # Java has no free functions: five `deserialize` methods are narrowed by the value's name as before
    got = _calls(make_repo, {
        "pom.xml": "<project/>\n",
        "src/main/java/a/TypeSerializer.java": "package a;\npublic class TypeSerializer {\n"
                                               "    public Object deserialize(int x, int y) { return null; }\n}\n",
        **{f"src/main/java/a/Reader{i}.java": f"package a;\npublic class Reader{i} {{\n"
           f"    public Object deserialize(int x, int y) {{ return null; }}\n}}\n" for i in range(4)},
        "src/main/java/a/Pojo.java": "package a;\npublic class Pojo {\n    public Object read(int x) {\n"
                                     "        var serializer = pick();\n        return serializer.deserialize(x, 1);\n    }\n}\n",
    }, ["."])
    assert any(k[0].endswith("Pojo#read/1") and k[1].endswith("TypeSerializer#deserialize/2") for k in got), got


def test_a_generated_route_handler_is_no_call_target_of_other_files(make_repo):
    gen = ('// Code generated by oapi-codegen. DO NOT EDIT.\npackage ports\n\nimport "github.com/go-chi/chi/v5"\n\n'
           'type ServerInterfaceWrapper struct{}\n\nfunc (siw *ServerInterfaceWrapper) CancelTraining(w W, r R) {}\n\n'
           'func Handler(r chi.Router, wrapper ServerInterfaceWrapper) {\n\tr.Delete("/t", wrapper.CancelTraining)\n}\n')
    got = _calls(make_repo, {
        "go.mod": "module shop\n", "ports/api.gen.go": gen,
        "adapters/grpc.go": "package adapters\n\ntype TrainerGrpc struct{ client C }\n\n"
                            "func (s TrainerGrpc) CancelTraining(ctx X, id string) {\n\ts.client.CancelTraining(ctx, id)\n}\n"},
        ["."])
    assert not any(to.endswith("ServerInterfaceWrapper#CancelTraining/2") for _, to in got)


def test_a_constructor_parameter_types_its_receiver_over_a_class_of_the_same_name(make_repo):
    # `db: Jdbc` is a class parameter; a `case class Db` elsewhere must not claim `db.update`
    got = _calls(make_repo, {
        "build.sbt": 'lazy val app = project in file(".")\n',
        "src/main/scala/acme/Jdbc.scala": "package acme\ntrait Jdbc:\n  def update(sql: String, params: Any*): Int\n",
        "src/main/scala/acme/Config.scala": "package acme\nfinal case class Db(host: String):\n  def url: String = host\n",
        "src/main/scala/acme/Repo.scala": "package acme\nfinal class Live(db: Jdbc):\n"
                                          "  def insert(id: String): Int =\n    db.update(\"INSERT\", id)\n"},
        ["."])
    assert any(f.endswith("Live#insert/1") and t.endswith("Jdbc#update/2") for f, t in got), got
