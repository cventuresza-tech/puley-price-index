"""Reading one App Store app page: the store's currency and the "In-App Purchases" list.

Apple renders app pages with the data inline: a schema.org SoftwareApplication block (name and the store's currency in
offers.priceCurrency) and a JSON blob ("serialized-server-data") whose "information" shelf holds the In-App Purchases
annotation as name/price text pairs. Pages are requested with ?l=en-GB, so labels and plan names come back in English.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

_LD = re.compile(r'<script id=["\']?software-application["\']? type="application/ld\+json">(.*?)</script>', re.S)
_SERVER = re.compile(r'<script type="application/json" id="serialized-server-data">(.*?)</script>', re.S)
IAP_TITLES = {"in-app purchases", "in-app purchase"}


@dataclass
class AppPage:
    name: str | None = None
    currency: str | None = None
    iaps: list[tuple[str, str]] = field(default_factory=list)  # (plan name, formatted price), in Apple's order
    has_iap_shelf: bool = False


class PageError(ValueError):
    """The page isn't an app page we can read (Apple changed it, or sent an error page)."""


def parse_app_page(html: str) -> AppPage:
    page = AppPage()
    m = _LD.search(html)
    if m:
        try:
            ld = json.loads(m.group(1))
            page.name = ld.get("name")
            offers = ld.get("offers") or {}
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            page.currency = (offers.get("priceCurrency") or "").upper() or None
        except json.JSONDecodeError:
            pass
    s = _SERVER.search(html)
    if not s:
        if page.name:
            return page
        raise PageError("no app data on the page")
    try:
        data = json.loads(s.group(1))
    except json.JSONDecodeError as e:
        raise PageError(f"app data isn't JSON: {e}") from None
    for shelf in _information_shelves(data):
        for item in shelf.get("items") or []:
            title = str(item.get("title") or "").strip().lower()
            pairs = [p for p in item.get("items") or [] if isinstance(p, dict) and p.get("$kind") == "textPair"]
            if title in IAP_TITLES:
                page.has_iap_shelf = True
                page.iaps = [(str(p.get("leadingText") or "").strip(), str(p.get("trailingText") or "").strip()) for p in pairs
                             if p.get("leadingText") and p.get("trailingText")]
    return page


def _information_shelves(data) -> list[dict]:
    """Every shelfMapping.information block in the payload (normally one)."""
    out = []
    stack = [data]
    while stack:
        o = stack.pop()
        if isinstance(o, dict):
            sm = o.get("shelfMapping")
            if isinstance(sm, dict) and isinstance(sm.get("information"), dict):
                out.append(sm["information"])
            stack.extend(v for v in o.values() if isinstance(v, (dict, list)))
        elif isinstance(o, list):
            stack.extend(v for v in o if isinstance(v, (dict, list)))
    return out
