
CREATE TABLE IF NOT EXISTS documents (
    id              SERIAL          PRIMARY KEY,
    document_type   VARCHAR(50)     NOT NULL,   -- INVOICE / PAYMENT
    file_name       VARCHAR(255)    NOT NULL,
    file_type       VARCHAR(20)     NOT NULL,   -- pdf / csv / xlsx
    storage_path    TEXT            NOT NULL,
    status          VARCHAR(50)     NOT NULL,   -- UPLOADED / PARSED / FAILED
    uploaded_at     TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_document_type ON documents (document_type);
CREATE INDEX IF NOT EXISTS idx_documents_status        ON documents (status);
