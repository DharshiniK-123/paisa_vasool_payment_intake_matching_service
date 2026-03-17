
CREATE TABLE IF NOT EXISTS scheduler_settings (
    id          INTEGER     PRIMARY KEY DEFAULT 1,
    run_hour    INTEGER     NOT NULL DEFAULT 9,
    run_minute  INTEGER     NOT NULL DEFAULT 0,
    is_enabled  BOOLEAN     NOT NULL DEFAULT TRUE,

    CONSTRAINT scheduler_settings_single_row CHECK (id = 1)
);

-- Seed the one default row if it doesn't exist yet
INSERT INTO scheduler_settings (id, run_hour, run_minute, is_enabled)
VALUES (1, 9, 0, TRUE)
ON CONFLICT (id) DO NOTHING;
