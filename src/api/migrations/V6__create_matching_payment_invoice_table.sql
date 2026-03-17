
CREATE TABLE IF NOT EXISTS matching_payment_invoice (
    id                  SERIAL          PRIMARY KEY,
    payment_detail_id   INTEGER         NOT NULL REFERENCES payment_details(id) ON DELETE RESTRICT,
    invoice_id          INTEGER                  REFERENCES invoice_data(id)    ON DELETE SET NULL,
    matched_amount      NUMERIC(12, 2)  NOT NULL,
    amount_pending      NUMERIC(12, 2),
    match_score         NUMERIC(5, 2)   NOT NULL,
    match_status        VARCHAR(50)     NOT NULL,   -- FULL / PARTIAL / FAILED
    match_reason        TEXT,
    created_at          TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_matching_payment_detail_id ON matching_payment_invoice (payment_detail_id);
CREATE INDEX IF NOT EXISTS idx_matching_invoice_id        ON matching_payment_invoice (invoice_id);
CREATE INDEX IF NOT EXISTS idx_matching_match_status      ON matching_payment_invoice (match_status);
