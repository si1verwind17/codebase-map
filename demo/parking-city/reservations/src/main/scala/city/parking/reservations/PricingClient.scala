package city.parking.reservations

import city.parking.common.Config
import zio.*
import zio.http.*
import zio.json.*

/** Calls the pricing service. The base URL comes from PRICING_URL. */
trait PricingClient:
  def quote(zoneId: String, minutes: Int): Task[Quote]

object PricingClient:

  val live: ZLayer[Client, Throwable, PricingClient] =
    ZLayer:
      for
        client <- ZIO.service[Client]
        base   <- Config.env("PRICING_URL")
      yield Live(client, base)

  private final class Live(client: Client, base: String) extends PricingClient:
    def quote(zoneId: String, minutes: Int): Task[Quote] =
      ZIO.scoped:
        for
          url  <- ZIO.fromEither(URL.decode(s"$base/v1/quote?zone=$zoneId&minutes=$minutes"))
          resp <- client.request(Request.get(url))
          body <- resp.body.asString
          q    <- ZIO.fromEither(body.fromJson[Quote]).mapError(new RuntimeException(_))
        yield q
