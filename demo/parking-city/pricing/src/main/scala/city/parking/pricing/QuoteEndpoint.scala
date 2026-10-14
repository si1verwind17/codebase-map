package city.parking.pricing

import sttp.model.StatusCode
import sttp.tapir.*
import sttp.tapir.generic.auto.*
import sttp.tapir.json.zio.*
import sttp.tapir.ztapir.*
import zio.json.*

final case class QuoteView(zoneId: String, cents: Long, currency: String, surge: Double)
    derives JsonCodec

final case class PricingError(error: String) derives JsonCodec

/** The one public route of pricing: GET /v1/quote?zone=..&minutes=.. */
object QuoteEndpoint:

  val quote =
    endpoint.get
      .in("v1" / "quote")
      .in(query[String]("zone"))
      .in(query[Int]("minutes"))
      .out(jsonBody[QuoteView])
      .errorOut(statusCode(StatusCode.NotFound).and(jsonBody[PricingError]))

  def routes(svc: PricingService): List[ZServerEndpoint[Any, Any]] =
    List(
      quote.zServerLogic((zone, minutes) =>
        svc.quote(zone, minutes).mapError(m => PricingError(m))
      )
    )
