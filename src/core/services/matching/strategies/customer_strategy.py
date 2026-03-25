from decimal import Decimal

from src.config.matching_config import MATCHING_CONFIG

from .base import BaseMatchStrategy, ScoreResult


class CustomerStrategy(BaseMatchStrategy):
    """
    Scores based on customer_id match between payment and invoice.
    Mismatch does NOT disqualify — it just adds no points and logs a reason.
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
        if payment.customer_id == invoice.customer_id:
            return ScoreResult(
                points=MATCHING_CONFIG.w_customer,
                reasons=["Customer ID matches between payment and invoice."],
                passed=True,
            )

        return ScoreResult(
            points=0,
            reasons=[
                f"Customer ID mismatch — payment customer: {payment.customer_id}, "
                f"invoice customer: {invoice.customer_id}."
            ],
            passed=True,  # mismatch is noted but does not disqualify
        )
