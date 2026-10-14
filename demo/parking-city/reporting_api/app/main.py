"""Reporting API: read-only. It never writes; it only reads reservations,
invoices and bay_status."""
from datetime import date

from fastapi import FastAPI, Query

from common_py.db import connect

app = FastAPI(title="reporting-api")


@app.get("/v1/reports/revenue")
def revenue(start: date = Query(...), end: date = Query(...)) -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT r.zone_id, date(r.starts_at) AS day, sum(i.cents) AS cents, count(*) AS bookings
            FROM invoices i
            JOIN reservations r ON r.id::text = i.reservation_id
            WHERE i.status = 'PAID' AND date(r.starts_at) BETWEEN %s AND %s
            GROUP BY r.zone_id, date(r.starts_at)
            ORDER BY day, r.zone_id
            """,
            (start, end),
        ).fetchall()
    return {
        "rows": [{"zone_id": z, "day": d.isoformat(), "cents": c, "bookings": n} for z, d, c, n in rows]
    }


@app.get("/v1/reports/occupancy")
def occupancy() -> dict:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT zone_id, count(*) AS bays, count(*) FILTER (WHERE occupied) AS occupied
            FROM bay_status
            GROUP BY zone_id
            ORDER BY zone_id
            """
        ).fetchall()
        open_bookings = conn.execute(
            "SELECT zone_id, count(*) FROM reservations WHERE status = 'PAID' AND ends_at > now() GROUP BY zone_id"
        ).fetchall()
    booked = dict(open_bookings)
    return {
        "zones": [
            {"zone_id": z, "bays": b, "occupied": o, "booked_now": booked.get(z, 0)} for z, b, o in rows
        ]
    }
