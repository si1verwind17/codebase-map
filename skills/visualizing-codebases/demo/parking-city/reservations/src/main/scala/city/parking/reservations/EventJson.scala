package city.parking.reservations

/** Shape of messages on the reservation-events topic. */
object EventJson:

  def created(r: Reservation): String =
    s"""{"type":"reservation.created","reservationId":"${r.id}","driverId":"${r.driverId}","zoneId":"${r.zoneId}","plate":"${r.plate}","amountCents":${r.quoteCents}}"""

  def cancelled(r: Reservation): String =
    s"""{"type":"reservation.cancelled","reservationId":"${r.id}","driverId":"${r.driverId}"}"""
