package city.parking.billing

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
