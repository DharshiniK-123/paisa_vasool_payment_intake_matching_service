import json
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.control.extraction.llm_client import get_llm
from src.data.models.postgres.aging_config import AgingConfig
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.invoice_data import InvoiceData
from src.data.models.postgres.reminder_log import ReminderLog
from src.utils.Email_util import send_email


async def _get_last_reminder(invoice_id: int, db: AsyncSession) -> ReminderLog | None:
    result = await db.execute(
        select(ReminderLog)
        .where(
            and_(
                ReminderLog.invoice_id == invoice_id,
                ReminderLog.status == "SENT",
            )
        )
        .order_by(ReminderLog.sent_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _is_frequency_due(last_reminder: ReminderLog | None, frequency_days: int) -> bool:
    if last_reminder is None:
        return True
    if last_reminder.sent_at is None:
        return True
    last_date = last_reminder.sent_at.date()
    next_due = last_date + timedelta(days=frequency_days)
    return bool(date.today() >= next_due)


def _safe_json_parse(raw: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    try:
        return cast(dict[Any, Any], json.loads(cleaned.strip()))
    except json.JSONDecodeError:
        return None


async def _generate_email(
    customer: Customer,
    invoice: InvoiceData,
    days_overdue: int,
    severity: str,
) -> dict:
    pending_amount = Decimal(str(invoice.total_amount)) - Decimal(str(invoice.paid_amount))
    tone_guide = {
        "LOW": "Gentle and friendly. Just a soft nudge.",
        "MEDIUM": "Polite and friendly. Assume it was an oversight. No pressure.",
        "HIGH": "Firm and professional. Request immediate action. "
        "Mention consequences politely.",
        "CRITICAL": "Urgent and formal. Mention escalation to senior management if not resolved.",
    }

    prompt = f"""
            You are a professional finance associate writing a payment reminder email on behalf of 
            PaisaVasool Finance Team.

            Customer name  : {customer.name}
            Invoice number : {invoice.invoice_number}
            Invoice date   : {invoice.invoice_date}
            Due date       : {invoice.due_date}
            Total amount   : {invoice.total_amount} {invoice.currency}
            Amount paid    : {invoice.paid_amount} {invoice.currency}
            Amount pending : {pending_amount} {invoice.currency}
            Days overdue   : {days_overdue} days
            Severity       : {severity}
            Tone guideline : {tone_guide.get(severity, "Professional and clear.")}

            Write a professional payment reminder email.
            Return ONLY a valid JSON object with no extra text, no markdown, no explanation:
            {{
                "subject": "concise email subject line",
                "body": "full professional email body"
            }}
            Always sign off with exactly:
            Regards,
            Finance Team
            PaisaVasool
            """

    def _fallback_email() -> dict:
        return {
            "subject": f"Payment Reminder — {invoice.invoice_number} ({days_overdue} days overdue)",
            "body": (
                f"Dear {customer.name},\n\n"
                f"This is a reminder that invoice {invoice.invoice_number} "
                f"for {pending_amount} {invoice.currency} is overdue by {days_overdue} days.\n\n"
                f"Please arrange payment at the earliest.\n\nRegards,\nFinance Team"
            ),
        }

    llm = get_llm()
    try:
        response = await llm.ainvoke(prompt)
        parsed = _safe_json_parse(response.content)
        if not parsed:
            return _fallback_email()
        return {
            "subject": parsed.get("subject") or f"Payment Reminder — {invoice.invoice_number}",
            "body": parsed.get("body") or _fallback_email()["body"],
        }
    except Exception as llm_exc:
        print(f"[LLM FAILED] {llm_exc}")
        return _fallback_email()


async def process_reminder(
    invoice: InvoiceData,
    days_overdue: int,
    config: AgingConfig,
    db: AsyncSession,
) -> ReminderLog | None:
    frequency = config.reminder_frequency if config.reminder_frequency else 1

    last_reminder = await _get_last_reminder(int(invoice.id), db)
    if not _is_frequency_due(last_reminder, int(frequency)):
        return None

    customer_result = await db.execute(select(Customer).where(Customer.id == invoice.customer_id))
    customer = customer_result.scalar_one_or_none()
    if not customer:
        return None

    if not customer.email:
        return None
    email = await _generate_email(customer, invoice, days_overdue, str(config.severity))

    status = "SENT"
    failure_reason = None

    try:
        print("before sending email")
        await send_email(
            to=str(customer.email),
            subject=email["subject"],
            body=email["body"],
        )

    except Exception as exc:
        status = "FAILED"
        failure_reason = str(exc)
        print(failure_reason)

    reminder = ReminderLog(
        customer_id=customer.id,
        invoice_id=invoice.id,
        severity=config.severity,
        subject=email["subject"],
        body=email["body"],
        channel="EMAIL",
        status=status,
        sent_at=datetime.now(UTC) if status == "SENT" else None,
    )
    db.add(reminder)
    await db.flush()
    return reminder
