from decimal import Decimal

from .strategies import (
    AmountStrategy,
    BaseMatchStrategy,
    ClosesBalanceStrategy,
    CurrencyStrategy,
    CustomerStrategy,
    InvoiceNumberStrategy,
)

DEFAULT_PIPELINE: list[BaseMatchStrategy] = [
    InvoiceNumberStrategy(),   # 50 exact / 30 partial  — passed=False if no hit
    CustomerStrategy(),        # 25
    CurrencyStrategy(),        # 5
    AmountStrategy(),          # 20 / 15 / 5
    ClosesBalanceStrategy(),   # 10 bonus
]

DEEP_MATCH_PIPELINE: list[BaseMatchStrategy] = [
    CustomerStrategy(),        # 25
    CurrencyStrategy(),        # 5
    AmountStrategy(),          # 20 / 15 / 5
    ClosesBalanceStrategy(),   # 10 bonus
]


def run_scoring_pipeline(
    payment,
    invoice,
    invoice_nos:         list[str],
    remaining_pay:       Decimal,
    inv_remaining:       Decimal,
    converted:           bool           = False,
    fx_rate:             Decimal | None = None,
    original_pay_amount: Decimal | None = None,
    pipeline:            list[BaseMatchStrategy] | None = None,
) -> tuple[int, list[str]]:
    """
    Run each strategy in order.
    - Accumulates points and reasons.
    - If any strategy returns passed=False, scoring stops immediately (score=0).
    - Final score is capped at 100.
    Returns (score, reasons).
    """
    active_pipeline = pipeline or DEFAULT_PIPELINE
    total_score     = 0
    all_reasons: list[str] = []

    for strategy in active_pipeline:
        result = strategy.score(
            payment=payment,
            invoice=invoice,
            invoice_nos=invoice_nos,
            remaining_pay=remaining_pay,
            inv_remaining=inv_remaining,
            converted=converted,
            fx_rate=fx_rate,
            original_pay_amount=original_pay_amount,
        )
        total_score  += result.points
        all_reasons  += result.reasons

        if not result.passed:
            return 0, all_reasons

    return min(total_score, 100), all_reasons
