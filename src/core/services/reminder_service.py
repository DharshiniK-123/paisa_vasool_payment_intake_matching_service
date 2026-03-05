import json
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.aging_config import AgingConfig
from src.data.models.postgres.reminder_log import ReminderLog
from src.control.extraction.llm_client import get_llm

async def _get_last_reminder(invoice_id: int, db: AsyncSession) -> ReminderLog | None:
    result = await db.execute(select(ReminderLog).where(and_(ReminderLog.invoice_id == invoice_id,ReminderLog.status     == "GENERATED",)).order_by(ReminderLog.sent_at.desc()).limit(1))
    return result.scalar_one_or_none()


def _is_frequency_due(last_reminder: ReminderLog | None, frequency_days: int) -> bool:
    if last_reminder is None:
        return True
    if last_reminder.sent_at is None:
        return True
    last_date = last_reminder.sent_at.date()
    next_due  = last_date + timedelta(days=frequency_days)
    return date.today() >= next_due


async def _generate_email(customer: Customer,invoice: InvoiceData,days_overdue: int,severity: str,) -> dict:
    pending_amount = Decimal(str(invoice.total_amount)) - Decimal(str(invoice.paid_amount))
    tone_guide = {
        "MEDIUM":   "Polite and friendly. Assume it was an oversight. No pressure.",
        "HIGH":     "Firm and professional. Request immediate action. Mention consequences politely.",
        "CRITICAL": "Urgent and formal. Mention escalation to senior management if not resolved.",
    }
    prompt = f"""
    You are a professional finance associate writing a payment reminder email on behalf of your company.
    
    Customer name    : {customer.name}
    Invoice number   : {invoice.invoice_number}
    Invoice date     : {invoice.invoice_date}
    Due date         : {invoice.due_date}
    Total amount     : {invoice.total_amount} {invoice.currency}
    Amount paid      : {invoice.paid_amount} {invoice.currency}
    Amount pending   : {pending_amount} {invoice.currency}
    Days overdue     : {days_overdue} days
    Severity         : {severity}
    Tone guideline   : {tone_guide.get(severity, "Professional and clear.")}
    
    Write a professional payment reminder email.
    Return ONLY a valid JSON object with no extra text:
    {{
        "subject": "concise email subject line",
        "body": "full professional email body"
    }}
    """
    llm = get_llm()
    try:
        response = await llm.ainvoke(prompt)
        raw      = response.content.strip().strip("```json").strip("```").strip()
        parsed   = json.loads(raw)
        return {
            "subject": parsed.get("subject", f"Payment Reminder — {invoice.invoice_number}"),
            "body":    parsed.get("body", ""),
        }
    except Exception as e:
        return {
            "subject": f"Payment Reminder — {invoice.invoice_number} ({days_overdue} days overdue)",
            "body": (
                f"Dear {customer.name},\n\n"
                f"This is a reminder that invoice {invoice.invoice_number} "
                f"for {pending_amount} {invoice.currency} is overdue by {days_overdue} days.\n\n"
                f"Please arrange payment at the earliest.\n\n"
                f"Regards,\nFinance Team"
            ),
        }


async def process_reminder(invoice: InvoiceData,days_overdue: int,config: AgingConfig,db: AsyncSession,) -> ReminderLog | None:
    last_reminder = await _get_last_reminder(invoice.id, db)
    if not _is_frequency_due(last_reminder, config.reminder_frequency):
        return None  
    customer_result = await db.execute(select(Customer).where(Customer.id == invoice.customer_id))
    customer = customer_result.scalar_one_or_none()
    if not customer:
        return None
    try:
        email   = await _generate_email(customer, invoice, days_overdue, config.severity)
        status  = "GENERATED"
    except Exception:
        email   = {"subject": "", "body": ""}
        status  = "FAILED"

    from datetime import datetime, timezone
    reminder = ReminderLog(
        customer_id = customer.id,
        invoice_id  = invoice.id,
        severity    = config.severity,
        subject     = email["subject"],
        body        = email["body"],
        channel     = "EMAIL",
        status      = status,
        sent_at     = datetime.now(timezone.utc), 
    )
    db.add(reminder)
    await db.flush()
    await db.commit()

    return reminder