
CREATE TABLE IF NOT EXISTS aging_config (
    id                  SERIAL          PRIMARY KEY,
    severity            VARCHAR(50)     NOT NULL UNIQUE,   -- LOW / MEDIUM / HIGH / CRITICAL
    due_days_from       INTEGER         NOT NULL,
    due_days_to         INTEGER,
    reminder_frequency  INTEGER,
    is_active           BOOLEAN         NOT NULL
);
