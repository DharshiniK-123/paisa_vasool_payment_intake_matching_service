
CREATE TABLE IF NOT EXISTS payment_details (
    id                  SERIAL          PRIMARY KEY,
    document_id         INTEGER         NOT NULL REFERENCES documents(id)  ON DELETE RESTRICT,
    customer_id         INTEGER         NOT NULL REFERENCES customers(id)  ON DELETE RESTRICT,
    invoice_no          VARCHAR(100)    NOT NULL,
    payment_amount      NUMERIC(12, 2)  NOT NULL,
    currency            VARCHAR(10)     NOT NULL DEFAULT 'INR',
    paid_date           DATE            NOT NULL,
    payment_reference   VARCHAR(100),
    is_deleted          BOOLEAN         NOT NULL DEFAULT FALSE,

    CONSTRAINT unique_invoice_payment_reference
        UNIQUE (invoice_no, payment_reference)
);

CREATE INDEX IF NOT EXISTS idx_payment_details_customer_id ON payment_details (customer_id);
CREATE INDEX IF NOT EXISTS idx_payment_details_invoice_no  ON payment_details (invoice_no);
CREATE INDEX IF NOT EXISTS idx_payment_details_is_deleted  ON payment_details (is_deleted);
