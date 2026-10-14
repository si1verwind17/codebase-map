package city.parking.reservations

import java.util.UUID
import sttp.model.StatusCode
import sttp.tapir.*
import sttp.tapir.generic.auto.*
import sttp.tapir.json.zio.*
import sttp.tapir.ztapir.*

/** Public HTTP surface of the reservations service. */
object ReservationEndpoints:

  private val base = endpoint.in("v1" / "reservations")

  private val errors = oneOf[ErrorBody](
    oneOfVariant(StatusCode.NotFound, jsonBody[ErrorBody]),
    oneOfVariant(StatusCode.Conflict, jsonBody[ErrorBody]),
    oneOfVariant(StatusCode.BadGateway, jsonBody[ErrorBody])
  )

  val create =
    base.post
      .in(jsonBody[NewReservation])
      .out(statusCode(StatusCode.Created).and(jsonBody[Reservation]))
      .errorOut(errors)

  val get =
    base.get
      .in(path[UUID]("id"))
      .out(jsonBody[Reservation])
      .errorOut(errors)

  val cancel =
    base.post
      .in(path[UUID]("id") / "cancel")
      .out(jsonBody[Reservation])
      .errorOut(errors)

  def routes(svc: ReservationService): List[ZServerEndpoint[Any, Any]] =
    List(
      create.zServerLogic(r => svc.create(r).mapError(toBody)),
      get.zServerLogic(id => svc.find(id).mapError(toBody)),
      cancel.zServerLogic(id => svc.cancel(id).mapError(toBody))
    )

  private def toBody(e: ReservationError): ErrorBody = e match
    case ReservationError.NotFound(id)   => ErrorBody(s"reservation $id not found")
    case ReservationError.Unavailable(r) => ErrorBody(r)
    case ReservationError.Upstream(m)    => ErrorBody(m)
