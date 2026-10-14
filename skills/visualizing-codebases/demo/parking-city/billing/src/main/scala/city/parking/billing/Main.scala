package city.parking.billing

import city.parking.common.{EventProducer, Jdbc}
import sttp.tapir.server.ziohttp.ZioHttpInterpreter
import zio.*
import zio.http.*

object Main extends ZIOAppDefault:

  private val http =
    ZIO.serviceWithZIO[BillingService]: svc =>
      Server.serve(ZioHttpInterpreter().toHttp(SettleEndpoint.routes(svc)))

  val run =
    (ReservationEventsConsumer.run.forkScoped *> http)
      .provide(
        Server.defaultWithPort(8080),
        Jdbc.live,
        EventProducer.live,
        InvoiceRepo.live,
        StripeCharger.live,
        ReceiptStore.live,
        DeadLetters.live,
        BillingService.live,
        Scope.default
      )
