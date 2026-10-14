"""Not a DAG: the refund-correction statement that daily_revenue_rollup runs
after it has written the day's totals (late refunds lower earlier days)."""

SUBTRACT_REFUNDS = """
UPDATE daily_revenue d
SET cents = d.cents - x.refunded
FROM (
    SELECT date(r.starts_at) AS day, r.zone_id, sum(i.cents) AS refunded
    FROM invoices i JOIN reservations r ON r.id::text = i.reservation_id
    WHERE i.status = 'REFUNDED' AND r.starts_at > now() - interval '3 days'
    GROUP BY 1, 2
) x
WHERE d.day = x.day AND d.zone_id = x.zone_id
"""
