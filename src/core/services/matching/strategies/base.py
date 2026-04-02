from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class ScoreResult:
    points:  int
    reasons: list[str]
    passed:  bool = True


class BaseMatchStrategy(ABC):
    """
    Each strategy scores ONE signal (invoice number, amount, customer, currency).
    Return passed=False to hard-disqualify — no further strategies will run.
    """

    @abstractmethod
    def score(
        self,
        payment,
        invoice,
        invoice_nos:   list[str],
        remaining_pay: Decimal,
        inv_remaining: Decimal,
        **kwargs,
    ) -> ScoreResult:
        ...
