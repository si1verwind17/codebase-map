package city.parking.reservations

import java.time.Instant
import java.util.UUID
import zio.json.*

final case class NewReservation(
    driverId: String,
    zoneId: String,
    plate: String,
    startsAt: Instant,
    endsAt: Instant
) derives JsonCodec

final case class Reservation(
    id: UUID,
    driverId: String,
    zoneId: String,
    plate: String,
    startsAt: Instant,
    endsAt: Instant,
    status: String,
    quoteCents: Long,
    paymentIntentId: Option[String]
) derives JsonCodec

final case class Quote(zoneId: String, cents: Long, currency: String, surge: Double)
    derives JsonCodec

enum ReservationError:
  case NotFound(id: UUID)
  case Unavailable(reason: String)
  case Upstream(msg: String)

final case class ErrorBody(error: String) derives JsonCodec
