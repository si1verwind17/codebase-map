package city.parking.reservations

import city.parking.common.Jdbc
import java.sql.ResultSet
import java.util.UUID
import zio.*

/** All SQL of this service lives here. Owns the reservations and
  * reservation_outbox tables.
  */
trait ReservationRepo:
  def insert(r: Reservation): Task[Unit]
  def find(id: UUID): Task[Option[Reservation]]
  def markCancelled(id: UUID): Task[Boolean]
  def setPaymentIntent(id: UUID, intentId: String): Task[Unit]
  def pendingOutbox(limit: Int): Task[List[OutboxRow]]
  def markSent(id: Long): Task[Unit]

final case class OutboxRow(id: Long, reservationId: UUID, eventType: String, payload: String)

object ReservationRepo:

  val live: ZLayer[Jdbc, Nothing, ReservationRepo] = ZLayer.fromFunction(Live(_))

  private final class Live(db: Jdbc) extends ReservationRepo:

    def insert(r: Reservation): Task[Unit] =
      db.transaction: c =>
        val ins = c.prepareStatement(
          """INSERT INTO reservations
            |  (id, driver_id, zone_id, plate, starts_at, ends_at, status, quote_cents)
            |VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)""".stripMargin
        )
        ins.setObject(1, r.id)
        ins.setString(2, r.driverId)
        ins.setString(3, r.zoneId)
        ins.setString(4, r.plate)
        ins.setObject(5, java.sql.Timestamp.from(r.startsAt))
        ins.setObject(6, java.sql.Timestamp.from(r.endsAt))
        ins.setLong(7, r.quoteCents)
        ins.executeUpdate()
        val out = c.prepareStatement(
          "INSERT INTO reservation_outbox (reservation_id, event_type, payload) VALUES (?, 'reservation.created', ?::jsonb)"
        )
        out.setObject(1, r.id)
        out.setString(2, EventJson.created(r))
        out.executeUpdate()
      .unit

    def find(id: UUID): Task[Option[Reservation]] =
      db.query(
        """SELECT id, driver_id, zone_id, plate, starts_at, ends_at, status, quote_cents, payment_intent_id
          |FROM reservations WHERE id = ?""".stripMargin,
        id
      )(read).map(_.headOption)

    def markCancelled(id: UUID): Task[Boolean] =
      db.update(
        "UPDATE reservations SET status = 'CANCELLED' WHERE id = ? AND status IN ('PENDING', 'PAID')",
        id
      ).map(_ > 0)

    def setPaymentIntent(id: UUID, intentId: String): Task[Unit] =
      db.update("UPDATE reservations SET payment_intent_id = ? WHERE id = ?", intentId, id).unit

    def pendingOutbox(limit: Int): Task[List[OutboxRow]] =
      db.query(
        "SELECT id, reservation_id, event_type, payload FROM reservation_outbox WHERE sent_at IS NULL ORDER BY id LIMIT ?",
        limit
      )(rs => OutboxRow(rs.getLong(1), rs.getObject(2, classOf[UUID]), rs.getString(3), rs.getString(4)))

    def markSent(id: Long): Task[Unit] =
      db.update("UPDATE reservation_outbox SET sent_at = now() WHERE id = ?", id).unit

    private def read(rs: ResultSet): Reservation =
      Reservation(
        rs.getObject(1, classOf[UUID]), rs.getString(2), rs.getString(3), rs.getString(4),
        rs.getTimestamp(5).toInstant, rs.getTimestamp(6).toInstant, rs.getString(7),
        rs.getLong(8), Option(rs.getString(9))
      )
