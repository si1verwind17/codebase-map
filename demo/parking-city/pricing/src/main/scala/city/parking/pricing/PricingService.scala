package city.parking.pricing

import java.time.{Instant, ZoneOffset}
import zio.*

trait PricingService:
  def quote(zoneId: String, minutes: Int): IO[String, QuoteView]

object PricingService:

  val live: ZLayer[TariffRepo & SharedCache & Geocoder, Nothing, PricingService] =
    ZLayer.fromFunction(Live(_, _, _))

  private final class Live(repo: TariffRepo, cache: SharedCache, geo: Geocoder) extends PricingService:

    def quote(zoneId: String, minutes: Int): IO[String, QuoteView] =
      for
        tariff <- repo.tariff(zoneId).orDie.someOrFail(s"no tariff for zone $zoneId")
        _      <- ensureCoordinates(zoneId).ignore
        occ    <- cache.occupancyPercent(zoneId).orElseSucceed(None)
        hour = Instant.now().atOffset(ZoneOffset.UTC).getHour
        demand <- repo.demandIndex(zoneId, hour).orElseSucceed(None)
        surge = surgeFactor(occ.getOrElse(50), demand.getOrElse(1.0))
        cents = math.round(tariff.centsPerHour * (minutes / 60.0) * surge)
      yield QuoteView(zoneId, cents, tariff.currency, surge)

    /** Fills in zone coordinates the first time a zone is quoted. */
    private def ensureCoordinates(zoneId: String): Task[Unit] =
      repo.zone(zoneId).flatMap:
        case Some(z) if z.lat.isEmpty =>
          geo.geocode(z.address).flatMap:
            case Some((lat, lng)) => repo.saveCoordinates(zoneId, lat, lng)
            case None             => ZIO.unit
        case _ => ZIO.unit

    private def surgeFactor(occupancyPercent: Int, demandIndex: Double): Double =
      val base = if occupancyPercent >= 90 then 1.5 else if occupancyPercent >= 70 then 1.2 else 1.0
      math.min(2.0, base * demandIndex)
