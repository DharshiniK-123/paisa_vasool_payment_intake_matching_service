-- V9: Create exchange_rates table
-- Stores historical FX rates fetched from Frankfurter on the payment date.
-- One row per (rate_date, from_currency, to_currency) — used as an audit
-- trail proving the exact rate applied during currency conversion matching.

CREATE TABLE IF NOT EXISTS exchange_rates (
    id            SERIAL PRIMARY KEY,
    rate_date     DATE         NOT NULL,
    from_currency VARCHAR(10)  NOT NULL,
    to_currency   VARCHAR(10)  NOT NULL,
    rate          NUMERIC(20, 8) NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_exchange_rate_date_pair
        UNIQUE (rate_date, from_currency, to_currency)
);

CREATE INDEX IF NOT EXISTS idx_exchange_rates_date_pair
    ON exchange_rates (rate_date, from_currency, to_currency);
