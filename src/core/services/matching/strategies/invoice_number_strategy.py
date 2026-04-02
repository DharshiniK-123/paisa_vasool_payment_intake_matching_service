from decimal import Decimal

from src.config.matching_config import MATCHING_CONFIG
from src.utils.normalize import _normalize

from .base import BaseMatchStrategy, ScoreResult


class InvoiceNumberStrategy(BaseMatchStrategy):
    """
    Scores based on how well the invoice number matches
    the payment reference. No match at all = hard disqualify.
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
        inv_num = _normalize(invoice.invoice_number or "")

        exact_hit   = any(n == inv_num for n in invoice_nos)
        partial_hit = (not exact_hit) and any(
            inv_num in n or n in inv_num for n in invoice_nos
        )

        if exact_hit:
            return ScoreResult(
                points=MATCHING_CONFIG.w_inv_exact,
                reasons=[f"Invoice number '{invoice.invoice_number}' matched exactly."],
                passed=True,
            )

        if partial_hit:
            return ScoreResult(
                points=MATCHING_CONFIG.w_inv_partial,
                reasons=[
                    f"Invoice number '{invoice.invoice_number}' partially matched "
                    f"the payment reference '{payment.invoice_no}'."
                ],
                passed=True,
            )

        return ScoreResult(
            points=0,
            reasons=[
                f"Invoice number '{invoice.invoice_number}' was not found "
                f"in the payment reference '{payment.invoice_no}'."
            ],
            passed=False,
        )
