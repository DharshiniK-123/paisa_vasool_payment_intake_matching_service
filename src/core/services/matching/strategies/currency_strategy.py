from decimal import Decimal

from src.config.matching_config import MATCHING_CONFIG

from .base import BaseMatchStrategy, ScoreResult


class CurrencyStrategy(BaseMatchStrategy):
    """
    Scores currency match.
    - Same currency       → full points, no extra info needed
    - FX converted        → full points + conversion details logged
    Both cases pass. Currency mismatch without conversion is handled
    upstream (currency_mismatches loop) before this strategy runs.
    """

    def score(
        self,
        payment,
        invoice,
        invoice_nos:   list[str],
        remaining_pay: Decimal,
        inv_remaining: Decimal,
        converted:          bool            = False,
        fx_rate:            Decimal | None  = None,
        original_pay_amount: Decimal | None = None,
        **kwargs,
    ) -> ScoreResult:
        if converted and fx_rate is not None and original_pay_amount is not None:
            return ScoreResult(
                points=MATCHING_CONFIG.w_currency,
                reasons=[
                    f"Currency mismatch resolved via automatic conversion: "
                    f"payment currency {payment.currency} → invoice currency {invoice.currency}. "
                    f"Exchange rate applied on payment date ({payment.paid_date}): "
                    f"1 {payment.currency} = {fx_rate:.8f} {invoice.currency}. "
                    f"Original payment amount: {payment.currency} {original_pay_amount:,.2f} "
                    f"converted to {invoice.currency} {remaining_pay:,.2f}."
                ],
                passed=True,
            )

        return ScoreResult(
            points=MATCHING_CONFIG.w_currency,
            reasons=[],
            passed=True,
        )
