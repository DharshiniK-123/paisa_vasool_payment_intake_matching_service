from decimal import Decimal

from src.config.matching_config import MATCHING_CONFIG

from .base import BaseMatchStrategy, ScoreResult


class ClosesBalanceStrategy(BaseMatchStrategy):
    """
    Bonus points when a payment exactly closes the remaining
    balance on a partially-paid invoice.
    """

    def score(
        self,
        payment,
        invoice,
        invoice_nos:   list[str],
        remaining_pay: Decimal,
        inv_remaining: Decimal,
        **kwargs,
    ) -> ScoreResult:
        already_matched = Decimal(str(invoice.total_amount)) - inv_remaining
        diff            = abs(remaining_pay - inv_remaining)

        if already_matched > 0 and diff == Decimal("0.00"):
            return ScoreResult(
                points=MATCHING_CONFIG.w_closes_partial,
                reasons=[
                    f"Payment closes the remaining balance on a partially-paid invoice "
                    f"(previously paid: {invoice.currency} {already_matched:,.2f})."
                ],
                passed=True,
            )

        return ScoreResult(points=0, reasons=[], passed=True)
