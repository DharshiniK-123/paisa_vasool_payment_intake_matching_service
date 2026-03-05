import re
from decimal import Decimal


def _normalize(ref: str) -> str:
    if not ref:
        return ""
    return re.sub(r"[\s\-/]", "", ref.upper())


