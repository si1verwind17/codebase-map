-- One Postgres (DB_HOST). Table owners are noted per table.

-- owner: reservations
CREATE TABLE reservations (
    id                UUID PRIMARY KEY,
    driver_id         TEXT        NOT NULL,
    zone_id           TEXT        NOT NULL,
    plate             TEXT        NOT NULL,
    starts_at         TIMESTAMPTZ NOT NULL,
    ends_at           TIMESTAMPTZ NOT NULL,
    status            TEXT        NOT NULL,   -- PENDING | PAID | CANCELLED | FAILED
    quote_cents       BIGINT      NOT NULL,
    payment_intent_id TEXT
);

CREATE TABLE reservation_outbox (
    id             BIGSERIAL PRIMARY KEY,
    reservation_id UUID        NOT NULL REFERENCES reservations (id),
    event_type     TEXT        NOT NULL,
    payload        JSONB       NOT NULL,
    sent_at        TIMESTAMPTZ
);

-- owner: pricing (reference data, edited by operations)
CREATE TABLE zones (
    id      TEXT PRIMARY KEY,
    name    TEXT NOT NULL,
    address TEXT NOT NULL,
    lat     DOUBLE PRECISION,
    lng     DOUBLE PRECISION
);

CREATE TABLE tariffs (
    zone_id        TEXT    NOT NULL REFERENCES zones (id),
    cents_per_hour BIGINT  NOT NULL,
    currency       TEXT    NOT NULL,
    active         BOOLEAN NOT NULL DEFAULT TRUE
);

-- owner: billing
CREATE TABLE invoices (
    id             UUID PRIMARY KEY,
    reservation_id TEXT NOT NULL UNIQUE,
    driver_id      TEXT NOT NULL,
    cents          BIGINT NOT NULL,
    status         TEXT NOT NULL,             -- PAID | REFUNDED
    receipt_key    TEXT,
    settled_at     TIMESTAMPTZ
);

-- owner: payments-webhook
CREATE TABLE payments (
    id                TEXT PRIMARY KEY,       -- Stripe event id
    payment_intent_id TEXT        NOT NULL,
    reservation_id    UUID,
    status            TEXT        NOT NULL,
    amount_cents      BIGINT      NOT NULL,
    received_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- owner: occupancy
CREATE TABLE bay_status (
    zone_id     TEXT        NOT NULL,
    bay_id      TEXT        NOT NULL,
    occupied    BOOLEAN     NOT NULL,
    plate       TEXT,
    since       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (zone_id, bay_id)
);

-- owner: nightly-jobs (aggregates)
CREATE TABLE daily_revenue (
    day         DATE   NOT NULL,
    zone_id     TEXT   NOT NULL,
    cents       BIGINT NOT NULL,
    PRIMARY KEY (day, zone_id)
);

CREATE TABLE zone_utilisation (
    day         DATE             NOT NULL,
    zone_id     TEXT             NOT NULL,
    utilisation DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (day, zone_id)
);

-- owner: demand-forecast (Flyte)
CREATE TABLE demand_forecast (
    zone_id      TEXT             NOT NULL,
    hour_of_day  INT              NOT NULL,
    demand_index DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (zone_id, hour_of_day)
);
