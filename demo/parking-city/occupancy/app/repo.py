"""SQL for the bay_status table (owned by this service)."""
from common_py.db import connect


def upsert_bay(zone_id: str, bay_id: str, occupied: bool, plate: str | None) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO bay_status (zone_id, bay_id, occupied, plate, since)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (zone_id, bay_id)
            DO UPDATE SET occupied = EXCLUDED.occupied,
                          plate = EXCLUDED.plate,
                          since = CASE WHEN bay_status.occupied = EXCLUDED.occupied
                                       THEN bay_status.since ELSE now() END
            """,
            (zone_id, bay_id, occupied, plate),
        )


def percent_full(zone_id: str) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT 100 * count(*) FILTER (WHERE occupied) / greatest(count(*), 1) "
            "FROM bay_status WHERE zone_id = %s",
            (zone_id,),
        ).fetchone()
    return int(row[0])


def bays_in_zone(zone_id: str) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT bay_id, occupied, plate, since FROM bay_status WHERE zone_id = %s ORDER BY bay_id",
            (zone_id,),
        ).fetchall()
    return [{"bay_id": r[0], "occupied": r[1], "plate": r[2], "since": r[3].isoformat()} for r in rows]


def overstayed(zone_id: str, bay_id: str) -> bool:
    """True when the bay's current reservation window ended more than 10 minutes ago."""
    with connect() as conn:
        row = conn.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM bay_status b
                JOIN reservations r ON r.zone_id = b.zone_id AND r.plate = b.plate
                WHERE b.zone_id = %s AND b.bay_id = %s AND b.occupied
                  AND r.ends_at < now() - interval '10 minutes'
            )
            """,
            (zone_id, bay_id),
        ).fetchone()
    return bool(row[0])
