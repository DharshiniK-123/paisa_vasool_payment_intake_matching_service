
CREATE TABLE IF NOT EXISTS invoice_data (
    id              SERIAL          PRIMARY KEY,
    document_id     INTEGER         NOT NULL REFERENCES documents(id)  ON DELETE RESTRICT,
    customer_id     INTEGER         NOT NULL REFERENCES customers(id)  ON DELETE RESTRICT,
    invoice_number  VARCHAR(100)    NOT NULL,
    invoice_date    DATE            NOT NULL,
    due_date        DATE            NOT NULL,
    total_amount    NUMERIC(12, 2)  NOT NULL,
    paid_amount     NUMERIC(12, 2)  NOT NULL DEFAULT 0.00,
    payment_status  VARCHAR(20)     NOT NULL DEFAULT 'UNPAID',  -- UNPAID / PARTIAL / PAID
    currency        VARCHAR(10)     NOT NULL DEFAULT 'INR',
    gl_code         VARCHAR(50),
    is_deleted      BOOLEAN         NOT NULL DEFAULT FALSE,
    updated_at      TIMESTAMPTZ     DEFAULT NOW(),

    CONSTRAINT unique_invoice_document_active
        UNIQUE (invoice_number, document_id, is_deleted)
);

CREATE INDEX IF NOT EXISTS idx_invoice_data_customer_id    ON invoice_data (customer_id);
CREATE INDEX IF NOT EXISTS idx_invoice_data_payment_status ON invoice_data (payment_status);
CREATE INDEX IF NOT EXISTS idx_invoice_data_due_date       ON invoice_data (due_date);
CREATE INDEX IF NOT EXISTS idx_invoice_data_is_deleted     ON invoice_data (is_deleted);
