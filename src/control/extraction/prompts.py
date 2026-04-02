INVOICE_EXTRACT_PROMPT = """
You are a strict financial document parser. Never guess or hallucinate field values.

Extract the following fields strictly:

  invoice_number : The invoice ID. null if missing.
  invoice_date   : Convert any date format to YYYY-MM-DD (e.g. "Oct 25 2012" → "2012-10-25").
  due_date       : Convert to YYYY-MM-DD. If absent, use invoice_date + 30 days.
  total_amount   : Final payable amount as a plain number
                  (Balance Due > Grand Total > Total > Amount Due).
  currency       : Infer from symbol: $=USD  ₹/Rs=INR  €=EUR  £=GBP. Default INR if unclear.
  customer_name  : Customer or bill-to name. null if not present.
  customer_email : Customer email. null if not present.
  gl_code        : GL / account code. null if not present.

Invoice text:
{raw_text}
"""

PAYMENT_EXTRACT_PROMPT = """
You are a strict financial document parser. Never guess or hallucinate field values.

Extract the following fields strictly:

  invoice_no        : Invoice number(s) this payment references. Comma-separate if multiple. null if not found.
  payment_amount    : Amount paid as a plain number, no symbols or commas.
  paid_date         : Convert any date format to YYYY-MM-DD.
  payment_reference : UTR / bank reference / transaction ID. null if not present.
  currency          : Infer from symbol: $=USD  ₹/Rs=INR  €=EUR  £=GBP. Default INR if unclear.
  customer_name     : Payer name. null if not present.
  customer_email    : Payer email. null if not present.

Payment document text:
{raw_text}
"""