package city.parking.reservations

import city.parking.common.EventProducer
import zio.*

/** Transactional outbox relay: polls reservation_outbox and publishes each row
  * to the Kafka topic reservation-events, keyed by reservation id so one
  * reservation's events stay in order. Consumers: billing, notifier.
  */
object OutboxRelay:

  val Topic = "reservation-events"

  val run: ZIO[ReservationRepo & EventProducer, Throwable, Nothing] =
    (for
      repo     <- ZIO.service[ReservationRepo]
      producer <- ZIO.service[EventProducer]
      rows     <- repo.pendingOutbox(100)
      _ <- ZIO.foreachDiscard(rows): row =>
             producer.publish(Topic, row.reservationId.toString, row.payload) *> repo.markSent(row.id)
    yield ()).repeat(Schedule.spaced(500.millis)).forever
