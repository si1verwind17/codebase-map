package city.parking.reservations

import java.time.Duration
import java.util.UUID
import zio.*

trait ReservationService:
  def create(req: NewReservation): IO[ReservationError, Reservation]
  def find(id: UUID): IO[ReservationError, Reservation]
  def cancel(id: UUID): IO[ReservationError, Reservation]

object ReservationService:

  val live: ZLayer[ReservationRepo & PricingClient & QuoteCache & StripeGateway, Nothing, ReservationService] =
    ZLayer.fromFunction(Live(_, _, _, _))

  private final class Live(
      repo: ReservationRepo,
      pricing: PricingClient,
      cache: QuoteCache,
      stripe: StripeGateway
  ) extends ReservationService:

    def create(req: NewReservation): IO[ReservationError, Reservation] =
      val minutes = Duration.between(req.startsAt, req.endsAt).toMinutes.toInt
      for
        _     <- ZIO.fail(ReservationError.Unavailable("end before start")).when(minutes <= 0)
        quote <- cachedQuote(req.zoneId, minutes)
        id  = UUID.randomUUID()
        res = Reservation(id, req.driverId, req.zoneId, req.plate, req.startsAt, req.endsAt,
                          "PENDING", quote.cents, None)
        _      <- repo.insert(res).mapError(e => ReservationError.Upstream(e.getMessage))
        intent <- stripe.createIntent(id.toString, quote.cents, quote.currency)
                    .mapError(e => ReservationError.Upstream(e.getMessage))
        _      <- repo.setPaymentIntent(id, intent).orDie
      yield res.copy(paymentIntentId = Some(intent))

    def find(id: UUID): IO[ReservationError, Reservation] =
      repo.find(id).orDie.someOrFail(ReservationError.NotFound(id))

    def cancel(id: UUID): IO[ReservationError, Reservation] =
      for
        ok  <- repo.markCancelled(id).orDie
        _   <- ZIO.fail(ReservationError.Unavailable("cannot cancel")).unless(ok)
        res <- find(id)
      yield res

    private def cachedQuote(zone: String, minutes: Int): IO[ReservationError, Quote] =
      val key = s"$zone:$minutes"
      cache.get(key).orElseSucceed(None).flatMap:
        case Some(q) => ZIO.succeed(q)
        case None =>
          pricing
            .quote(zone, minutes)
            .tap(q => cache.put(key, q).ignore)
            .mapError(e => ReservationError.Upstream(e.getMessage))
