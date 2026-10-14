package city.parking.billing

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
      s"RECEIPT ${inv.id}\nreservation ${inv.reservationId}\ntotal ${inv.cents / 100.0}".getBytes("UTF-8")
