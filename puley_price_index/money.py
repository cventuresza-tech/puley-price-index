"""Turning the App Store's formatted prices ("R399.99", "₺5.299,99", "¥3,000", "19,99 €") into numbers.

The store's currency comes from the page itself (schema.org priceCurrency), so this module never guesses the currency from a
symbol: "$19.99" could be US, Canadian, Australian or Singapore dollars. It only works out which mark is the decimal point.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# Currencies the App Store shows without minor units, and the few that have three decimals (ISO 4217).
ZERO_DECIMAL = {"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VND", "VUV", "XAF", "XOF", "XPF"}
THREE_DECIMAL = {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}

_NUMBER = re.compile(r"\d[\d.,'’   ]*\d|\d")


# Short forms some stores use: Indonesia prints "Rp 349ribu" (thousand) and "Rp 1,889juta" (1.889 million, decimal comma).
_COMPACT = [(re.compile(r"\d\s*(?:ribu|rb)\b", re.I), 1_000), (re.compile(r"\d\s*(?:juta|jt)\b", re.I), 1_000_000),
            (re.compile(r"\d\s*(?:miliar|M)\b"), 1_000_000_000), (re.compile(r"\d\s*[kK]\b"), 1_000)]


def parse_price(text: str, currency: str | None = None) -> Decimal | None:
    """The amount in `text`, in units of `currency` (not minor units). None when there is no number."""
    if not text:
        return None
    for rx, mult in _COMPACT:
        if rx.search(text):
            tok = max(_NUMBER.findall(text) or [""], key=len)
            digits = re.sub(r"[^\d.,]", "", tok)
            if not digits:
                return None
            i = max(digits.rfind(","), digits.rfind("."))
            num = digits if i < 0 else re.sub(r"\D", "", digits[:i]) + "." + digits[i + 1:]
            v = _dec(num)
            return (v * mult).quantize(Decimal("1")) if v is not None else None
    tokens = _NUMBER.findall(text)
    if not tokens:
        return None
    tok = max(tokens, key=len).strip()
    digits = re.sub(r"[^\d.,]", "", tok)
    cur = (currency or "").upper()
    if cur in ZERO_DECIMAL:
        # "¥3,000" and "₫59.000" are whole units; a stray ".00" (seen on some stores) is dropped
        whole = re.sub(r"[.,]\d{2}$", "", digits) if re.search(r"[.,]\d{2}$", digits) and len(re.sub(r"\D", "", digits)) > 2 else digits
        return _dec(re.sub(r"\D", "", whole))
    seps = [(i, ch) for i, ch in enumerate(digits) if ch in ".,"]
    if not seps:
        return _dec(digits)
    i, ch = seps[-1]
    tail = len(digits) - i - 1
    decimals = 3 if cur in THREE_DECIMAL else 2
    if tail == decimals or (tail in (1, 2) and decimals != 3) or (tail == 3 and cur in THREE_DECIMAL):
        whole, frac = digits[:i], digits[i + 1:]
        return _dec(re.sub(r"\D", "", whole) + "." + frac)
    return _dec(re.sub(r"\D", "", digits))  # the last mark groups thousands ("Rp 299.000", "Ft 7,990")


def _dec(s: str) -> Decimal | None:
    try:
        return Decimal(s) if s and s != "." else None
    except InvalidOperation:
        return None
