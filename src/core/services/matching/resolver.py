from decimal import Decimal

from src.config.matching_config import MATCHING_CONFIG
from src.core.enums import MatchStatus


def resolve_match(
    remaining_pay: Decimal,
    inv_remaining: Decimal,
) -> tuple[str, Decimal, Decimal]:
    """
    Determines match status and amounts.

    Returns:
        (match_status, matched_amount, amount_pending)

    Rules:
        OVERPAYMENT  — payment exceeds invoice beyond rounding tolerance
        FULL         — payment covers invoice (including within tolerance)
        PARTIAL      — payment is less than invoice outstanding
    """
    diff = abs(remaining_pay - inv_remaining)

    if remaining_pay > inv_remaining + MATCHING_CONFIG.rounding_tolerance:
        return MatchStatus.OVERPAYMENT, inv_remaining, Decimal("0.00")

    if diff <= MATCHING_CONFIG.rounding_tolerance or remaining_pay >= inv_remaining:
        return MatchStatus.FULL, inv_remaining, Decimal("0.00")

    return MatchStatus.PARTIAL, remaining_pay, inv_remaining - remaining_pay


def build_status_sentence(
    match_status:   str,
    invoice,
    payment,
    matched_amount: Decimal,
    amount_pending: Decimal,
    remaining_pay:  Decimal,
    inv_remaining:  Decimal,
    converted:      bool           = False,
    fx_rate:        Decimal | None = None,
) -> str:
    """Builds the human-readable outcome sentence appended to match_reason."""

    if match_status == MatchStatus.FULL:
        if converted and fx_rate:
            return (
                f"Invoice '{invoice.invoice_number}' fully matched after currency conversion. "
                f"Amount applied: {invoice.currency} {matched_amount:,.2f} "
                f"(equivalent to {payment.currency} "
                f"{(matched_amount / fx_rate).quantize(Decimal('0.01')):,.2f} "
                f"at rate 1 {payment.currency} = {fx_rate:.8f} {invoice.currency} "
                f"on {payment.paid_date})."
            )
        return (
            f"Invoice '{invoice.invoice_number}' has been fully matched. "
            f"Amount applied: {payment.currency} {matched_amount:,.2f}."
        )

    if match_status == MatchStatus.PARTIAL:
        return (
            f"Invoice '{invoice.invoice_number}' has been partially matched. "
            f"Amount applied: {invoice.currency} {matched_amount:,.2f}. "
            f"Outstanding balance remaining: {invoice.currency} {amount_pending:,.2f}."
        )

    if converted:
        excess = remaining_pay - inv_remaining
        return (
            f"Invoice '{invoice.invoice_number}' fully matched after currency conversion "
            f"but converted payment exceeds the invoice amount. "
            f"Amount applied: {invoice.currency} {matched_amount:,.2f}. "
            f"Converted excess: {invoice.currency} {excess:,.2f} — flagged for review."
        )
    return (
        f"Invoice '{invoice.invoice_number}' has been fully matched but the payment "
        f"exceeds the invoice amount. "
        f"Amount applied: {invoice.currency} {matched_amount:,.2f}. "
        f"Excess amount: {payment.currency} {remaining_pay - inv_remaining:,.2f} "
        "— flagged for review."
    )
