INVOICE_EXTRACT_PROMPT = """
You are a strict financial document parser. Never guess or hallucinate field values.

STEP 1 — Classify the document:
- INVOICE: has invoice number, line items or service description, due date, billed-to info
- PAYMENT: has transaction ID / UTR reference, payment confirmation, amount paid
- UNKNOWN: cannot determine

STEP 2 — If this is NOT an INVOICE:
  Set mismatch=true, detected_type=<PAYMENT or UNKNOWN>.
  Set ALL other fields to null.
  Do NOT attempt to extract any invoice fields.

STEP 3 — If this IS an INVOICE:
  Set mismatch=false, detected_type=null.
  Extract the following fields strictly:

  invoice_number : The invoice ID. If missing → set mismatch=true, detected_type=UNKNOWN.
  invoice_date   : Convert any date format to YYYY-MM-DD (e.g. "Oct 25 2012" → "2012-10-25").
  due_date       : Convert to YYYY-MM-DD. If absent, use invoice_date + 30 days.
  total_amount   : Final payable amount as a plain number 
                  (Balance Due > Grand Total > Total > Amount Due).
                   If zero or missing → set mismatch=true, detected_type=UNKNOWN.
  currency       : Infer from symbol: $=USD  ₹/Rs=INR  €=EUR  £=GBP. Default USD if unclear.
  customer_name  : Customer or bill-to name. null if not present.
  customer_email : Customer email. null if not present.
  gl_code        : GL / account code. null if not present.

Invoice text:
{raw_text}
"""

PAYMENT_EXTRACT_PROMPT = """
You are a strict financial document parser. Never guess or hallucinate field values.

STEP 1 — Classify the document:
- PAYMENT: has transaction ID / UTR reference, payment confirmation, amount paid
- INVOICE: has invoice number, line items or service description, due date, billed-to info
- UNKNOWN: cannot determine

STEP 2 — If this is NOT a PAYMENT:
  Set mismatch=true, detected_type=<INVOICE or UNKNOWN>.
  Set ALL other fields to null.
  Do NOT attempt to extract any payment fields.

STEP 3 — If this IS a PAYMENT:
  Set mismatch=false, detected_type=null.
  Extract the following fields strictly:

  invoice_no        : Invoice number(s) this payment references. Comma-separate if multiple.
                      null if not found.
  payment_amount    : Amount paid as a plain number, no symbols or commas. Must be > 0.
                      If zero or missing → set mismatch=true, detected_type=UNKNOWN.
  paid_date         : Convert any date format to YYYY-MM-DD.
  payment_reference : UTR / bank reference / transaction ID. null if not present.
  currency          : Infer from symbol: $=USD  ₹/Rs=INR  €=EUR  £=GBP. Default INR if unclear.
  customer_name     : Payer name. null if not present.
  customer_email    : Payer email. null if not present.

Payment document text:
{raw_text}
"""
