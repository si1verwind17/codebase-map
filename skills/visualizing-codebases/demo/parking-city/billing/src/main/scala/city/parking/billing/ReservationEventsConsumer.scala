package city.parking.billing

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
