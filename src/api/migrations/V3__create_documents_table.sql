CREATE TABLE IF NOT EXISTS documents (
    id              SERIAL          PRIMARY KEY,
    document_type   VARCHAR(50)     NOT NULL,
    file_name       VARCHAR(255)    NOT NULL,
    file_type       VARCHAR(20)     NOT NULL,
    storage_path    TEXT            NOT NULL,
    file_hash       VARCHAR(500)    NULL,        -- missing comma fixed
    status          VARCHAR(50)     NOT NULL,
    uploaded_at     TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_document_type ON documents (document_type);
CREATE INDEX IF NOT EXISTS idx_documents_status        ON documents (status);
CREATE INDEX IF NOT EXISTS idx_documents_file_hash     ON documents (file_hash);