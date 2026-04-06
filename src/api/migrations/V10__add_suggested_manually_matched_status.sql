
CREATE INDEX IF NOT EXISTS idx_matching_suggested
    ON matching_payment_invoice (payment_detail_id)
    WHERE match_status = 'SUGGESTED';

CREATE INDEX IF NOT EXISTS idx_matching_manually_matched
    ON matching_payment_invoice (payment_detail_id)
    WHERE match_status = 'MANUALLY_MATCHED';

COMMENT ON COLUMN matching_payment_invoice.match_status IS
    'FULL          — payment fully covers invoice
     PARTIAL       — payment partially covers invoice
     OVERPAYMENT   — payment exceeds invoice amount
     FAILED        — could not match, manual review required
     DUPLICATE     — payment already matched to this invoice
     SUGGESTED     — deep match candidate, pending human approval
     MANUALLY_MATCHED — human explicitly assigned payment to invoice';
