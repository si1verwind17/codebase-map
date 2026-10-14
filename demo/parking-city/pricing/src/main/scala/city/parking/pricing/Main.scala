package city.parking.pricing

import city.parking.common.Jdbc
import sttp.tapir.server.ziohttp.ZioHttpInterpreter
import zio.*
import zio.http.*

object Main extends ZIOAppDefault:

  val run =
    ZIO
      .serviceWithZIO[PricingService]: svc =>
        Server.serve(ZioHttpInterpreter().toHttp(QuoteEndpoint.routes(svc)))
      .provide(
        Server.defaultWithPort(8080),
        Client.default,
        Jdbc.live,
        TariffRepo.live,
        SharedCache.live,
        Geocoder.live,
        PricingService.live
      )
