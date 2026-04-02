import re

from src.utils.normalize import _normalize


def _extract_multiple_invoice_nos(invoice_no: str) -> list[str]:
    parts = re.split(r"[,;&\s]+and\s+|[,;&]+", invoice_no)
    return [_normalize(p) for p in parts if _normalize(p)]


