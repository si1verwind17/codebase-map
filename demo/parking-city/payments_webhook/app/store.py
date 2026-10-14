from common_py.db import connect


def record_payment(event_id: str, intent_id: str, reservation_id: str | None, status: str, cents: int) -> None:
    """Idempotent on the Stripe event id, so webhook retries are harmless."""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO payments (id, payment_intent_id, reservation_id, status, amount_cents)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (event_id, intent_id, reservation_id, status, cents),
        )


def mark_reservation(reservation_id: str, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE reservations SET status = %s WHERE id = %s AND status = 'PENDING'",
            (status, reservation_id),
        )
