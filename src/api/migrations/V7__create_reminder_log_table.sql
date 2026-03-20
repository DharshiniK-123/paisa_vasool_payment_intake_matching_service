
CREATE TABLE IF NOT EXISTS reminder_log (
    id          SERIAL          PRIMARY KEY,
    customer_id INTEGER         NOT NULL REFERENCES customers(id)   ON DELETE RESTRICT,
    invoice_id  INTEGER         NOT NULL REFERENCES invoice_data(id) ON DELETE RESTRICT,
    severity    VARCHAR(50)     NOT NULL,   -- LOW / MEDIUM / HIGH / CRITICAL
    subject     VARCHAR(255)    NOT NULL,
    body        TEXT            NOT NULL,
    channel     VARCHAR(50)     NOT NULL DEFAULT 'EMAIL',
    status      VARCHAR(50)     NOT NULL,   -- SENT / FAILED
    sent_at     TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reminder_log_customer_id ON reminder_log (customer_id);
CREATE INDEX IF NOT EXISTS idx_reminder_log_invoice_id  ON reminder_log (invoice_id);
CREATE INDEX IF NOT EXISTS idx_reminder_log_status      ON reminder_log (status);
CREATE INDEX IF NOT EXISTS idx_reminder_log_sent_at     ON reminder_log (sent_at);
