"""Self-contained helpers formerly imported from the sibling `pyungchon_land` project.

APT WATCH must run without any code outside this repository.
"""
import re
from decimal import Decimal, InvalidOperation


def price_manwon(value):
    """Numeric input and unitless strings are explicitly in KRW 10,000 (만원)."""
    if value is None or isinstance(value, bool):
        return None
    text = re.sub(r'[\s,]', '', str(value)).replace('만원', '').replace('만', '')
    if not re.fullmatch(r'\d+(?:\.\d+)?(?:억\d*(?:\.\d+)?)?', text):
        return None
    try:
        if '억' in text:
            eok, rest = text.split('억')
            result = Decimal(eok) * 10000 + Decimal(rest or '0')
        else:
            result = Decimal(text)
        return int(result) if result == int(result) and result > 0 else None
    except InvalidOperation:
        return None
