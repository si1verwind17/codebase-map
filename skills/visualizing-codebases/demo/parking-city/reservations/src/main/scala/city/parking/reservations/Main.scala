package city.parking.reservations

import city.parking.common.{EventProducer, Jdbc}
import sttp.tapir.server.ziohttp.ZioHttpInterpreter
import zio.*
import zio.http.*

object Main extends ZIOAppDefault:

  private val httpApp =
    ZIO.serviceWith[ReservationService](svc => ZioHttpInterpreter().toHttp(ReservationEndpoints.routes(svc)))

  val run =
    (for
      app <- httpApp
      _   <- OutboxRelay.run.forkScoped
      _   <- Server.serve(app)
    yield ())
      .provide(
        Server.defaultWithPort(8080),
        Client.default,
        Jdbc.live,
        EventProducer.live,
        ReservationRepo.live,
        PricingClient.live,
        QuoteCache.live,
        StripeGateway.live,
        ReservationService.live,
        Scope.default
      )
