from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MatchingConfig:
    rounding_tolerance:   Decimal = Decimal("1.00")
    min_match_score:      int     = 50   
    deep_match_threshold: int     = 45  

    w_inv_exact:      int = 50
    w_inv_partial:    int = 30
    w_customer:       int = 25
    w_amt_exact:      int = 20
    w_amt_tolerance:  int = 15
    w_amt_partial:    int = 5
    w_currency:       int = 5
    w_closes_partial: int = 10


MATCHING_CONFIG = MatchingConfig()
