from dataclasses import dataclass


@dataclass
class Text:
    subject: str
    short: str
    long: str


def render(event: dict) -> Text | None:
    kind = event.get("type")
    if kind == "reservation.created":
        cents = event.get("amountCents", 0)
        return Text(
            subject="Your parking spot is booked",
            short=f"Booked zone {event.get('zoneId')} for {cents / 100:.2f}.",
            long=f"Your reservation {event['reservationId']} is confirmed.\nTotal: {cents / 100:.2f}.",
        )
    if kind == "reservation.cancelled":
        return Text(
            subject="Reservation cancelled",
            short="Your reservation was cancelled.",
            long=f"Reservation {event['reservationId']} was cancelled and will be refunded.",
        )
    return None
