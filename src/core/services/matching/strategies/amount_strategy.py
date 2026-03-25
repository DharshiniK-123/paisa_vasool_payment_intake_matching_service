from decimal import Decimal

from src.config.matching_config import MATCHING_CONFIG

from .base import BaseMatchStrategy, ScoreResult


class AmountStrategy(BaseMatchStrategy):
    """
    Scores based on how well the payment amount matches
    the invoice outstanding balance.
    """

    def score(
        self,
        payment,
        invoice,
        invoice_nos:   list[str],
        remaining_pay: Decimal,
        inv_remaining: Decimal,
        converted: bool = False,
        **kwargs,
    ) -> ScoreResult:
        cfg    = MATCHING_CONFIG
        diff   = abs(remaining_pay - inv_remaining)
        label  = "Converted payment" if converted else "Payment"

        # Exact match
        if remaining_pay == inv_remaining:
            return ScoreResult(
                points=cfg.w_amt_exact,
                reasons=[
                    f"{label} amount ({invoice.currency} {remaining_pay:,.2f}) "
                    f"matches the outstanding invoice balance exactly."
                ],
                passed=True,
            )

        # Within rounding tolerance
        if diff <= cfg.rounding_tolerance:
            return ScoreResult(
                points=cfg.w_amt_tolerance,
                reasons=[
                    f"{label} amount ({invoice.currency} {remaining_pay:,.2f}) "
                    f"matches the outstanding balance within the rounding tolerance "
                    f"(±{cfg.rounding_tolerance})."
                ],
                passed=True,
            )

        # Partial payment (underpayment)
        if remaining_pay < inv_remaining:
            shortfall = inv_remaining - remaining_pay
            return ScoreResult(
                points=cfg.w_amt_partial,
                reasons=[
                    f"Partial payment received. {label}: "
                    f"{invoice.currency} {remaining_pay:,.2f}, "
                    f"Invoice outstanding: {invoice.currency} {inv_remaining:,.2f}. "
                    f"Shortfall: {invoice.currency} {shortfall:,.2f}."
                ],
                passed=True,
            )

        # Overpayment
        excess = remaining_pay - inv_remaining
        return ScoreResult(
            points=cfg.w_amt_partial,
            reasons=[
                f"{label} ({invoice.currency} {remaining_pay:,.2f}) exceeds the invoice "
                f"outstanding balance ({invoice.currency} {inv_remaining:,.2f}) "
                f"by {invoice.currency} {excess:,.2f}."
            ],
            passed=True,
        )
