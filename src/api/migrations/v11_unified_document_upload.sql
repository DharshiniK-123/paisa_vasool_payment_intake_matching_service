
ALTER TABLE documents
    DROP CONSTRAINT IF EXISTS documents_document_type_check;

ALTER TABLE documents
    ADD CONSTRAINT documents_document_type_check
    CHECK (document_type IN ('INVOICE', 'PAYMENT', 'UNKNOWN'));

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS classified_at TIMESTAMPTZ DEFAULT NULL;