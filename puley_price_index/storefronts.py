"""Which countries have an App Store, and what currency each store charges in.

Discovery opens an Apple app that every store carries (TestFlight) in each ISO 3166 country: a real store keeps its own country
code in the address and states its currency; a code without a store is sent to another store or answers 404. The result is
saved to data/storefronts.json and reused; run discovery again now and then (Apple adds stores rarely).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .fetch import Fetcher
from .parse import PageError, parse_app_page

PROBE_APP = (899247664, "testflight")


def discover(countries: dict[str, str], fetcher: Fetcher, log=print) -> dict[str, dict]:
    """countries: ISO alpha-2 (lowercase) -> name. Returns {cc: {"name", "currency"}} for every live store."""
    out: dict[str, dict] = {}
    for n, (cc, name) in enumerate(sorted(countries.items()), 1):
        url = f"https://apps.apple.com/{cc}/app/{PROBE_APP[1]}/id{PROBE_APP[0]}?l=en-GB"
        try:
            r = fetcher.get(url)
        except RuntimeError as e:
            log(f"{cc}: {e}")
            continue
        if r is None:
            continue
        final_cc = re.match(r"https://apps\.apple\.com/([a-z]{2})/", str(r.url))
        if not final_cc or final_cc.group(1) != cc:
            continue
        try:
            page = parse_app_page(r.text)
        except PageError:
            continue
        if page.currency:
            out[cc] = {"name": name, "currency": page.currency}
        if n % 25 == 0:
            log(f"  {n}/{len(countries)} checked, {len(out)} stores")
    return out


def load(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text())["storefronts"]
