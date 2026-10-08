"""Exchange rates (to compare stores in US dollars) and World Bank price levels (to say how expensive a price feels locally).

- Rates: the open access endpoint of ExchangeRate-API (https://www.exchangerate-api.com), one snapshot a day, US dollar base.
  Their terms ask for a credit link, which the site and the README carry.
- Price levels: the World Bank's PPP conversion factor (GDP, PA.NUS.PPP) divided by the official exchange rate (PA.NUS.FCRF),
  for the latest year that has both (CC BY 4.0). That ratio is the country's price level against the US (the World Bank's own
  ratio indicator, PA.NUS.PPPC.RF, was retired). A price of $20 in a country whose ratio is 0.4 weighs on local budgets like
  $50 does in the US: feels_like_usd = usd / ratio.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .fetch import http_get

FX_URL = "https://open.er-api.com/v6/latest/USD"
WB_URL = "https://api.worldbank.org/v2/country/all/indicator/{}"


def fetch_rates(data: Path, log=print) -> Path:
    out = data / "rates"
    out.mkdir(parents=True, exist_ok=True)
    r = _get_json(FX_URL)
    if r.get("result") != "success":
        raise RuntimeError(f"exchange rates unavailable: {r.get('error-type') or r}")
    day = datetime.fromtimestamp(r["time_last_update_unix"], timezone.utc).strftime("%Y-%m-%d")
    fx = {"date": day, "base": "USD", "source": "ExchangeRate-API open access (https://www.exchangerate-api.com)",
          "rates": r["rates"]}
    path = out / f"fx-{day}.json"
    path.write_text(json.dumps(fx, indent=1, sort_keys=True))
    log(f"exchange rates for {day}: {len(fx['rates'])} currencies")
    levels = out / "price-levels.json"
    if not levels.exists() or _age_days(levels) > 30:
        fetch_price_levels(levels, log=log)
    return path


def _get_json(url: str, params: dict | None = None, tries: int = 4):
    import time
    for attempt in range(1, tries + 1):
        try:
            return http_get(url, params=params, timeout=120).json()
        except (OSError, ValueError):
            if attempt == tries:
                raise
            time.sleep(10 * attempt)


def _wb(indicator: str) -> dict[str, dict[int, float]]:
    resp = _get_json(WB_URL.format(indicator), params={"format": "json", "per_page": 20000, "date": "2015:2030"})
    if len(resp) < 2 or not resp[1]:
        raise RuntimeError(f"World Bank {indicator} unavailable: {str(resp)[:200]}")
    out: dict[str, dict[int, float]] = {}
    for row in resp[1]:
        cc = (row.get("country") or {}).get("id", "")
        if len(cc) == 2 and row.get("value") is not None:
            out.setdefault(cc, {})[int(row["date"])] = float(row["value"])
    return out


LEVEL_BOUNDS = (0.1, 2.0)  # real price levels sit roughly between Nigeria (~0.13) and Switzerland (~1.1)


def fetch_price_levels(path: Path, log=print) -> None:
    """The latest year whose ratio agrees with the year before it (a real change, like Nigeria's 2024 devaluation, shows in
    two years running). Ratios outside LEVEL_BOUNDS mean mismatched units (Liberia's US dollar against the Liberian dollar)
    or a broken official rate (Lebanon); those countries get no price level. Bulgaria's PPP series is already in euros while
    its exchange-rate series is in leva, so its PPP figure is converted at the fixed 1.95583 leva per euro."""
    ppp, fx = _wb("PA.NUS.PPP"), _wb("PA.NUS.FCRF")
    latest: dict[str, dict] = {}
    dropped = []
    for cc, years in ppp.items():
        ratios = {}
        for y in sorted(set(years) & set(fx.get(cc, {}))):
            p_, f_ = years[y], fx[cc][y]
            if cc == "BG" and f_ > 1.5 and p_ < 0.9:
                p_ *= 1.95583
            if f_:
                ratios[y] = p_ / f_
        ys = sorted(ratios, reverse=True)
        pick = None
        for i, y in enumerate(ys):
            r = ratios[y]
            if not LEVEL_BOUNDS[0] <= r <= LEVEL_BOUNDS[1]:
                continue
            prev = ys[i + 1] if i + 1 < len(ys) else None
            if prev is None or abs(r / ratios[prev] - 1) <= 0.35:
                pick = y
                break
        if pick is None or pick < ys[0] - 3:  # nothing recent that holds together (Lebanon after 2019)
            dropped.append(cc)
            continue
        latest[cc] = {"ratio": round(ratios[pick], 4), "year": pick}
    if dropped:
        log(f"price levels left out (inconsistent World Bank series): {', '.join(sorted(dropped))}")
    doc = {"indicators": ["PA.NUS.PPP", "PA.NUS.FCRF"],
           "name": "Price level: PPP conversion factor (GDP) / official exchange rate, latest year with both",
           "source": "World Bank, World Development Indicators (CC BY 4.0)", "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "countries": dict(sorted(latest.items()))}
    path.write_text(json.dumps(doc, indent=1))
    log(f"price levels for {len(latest)} countries")


def latest_fx(data: Path, day: str) -> dict:
    """The newest exchange-rate snapshot on or before `day` (or the oldest one after it, for a first run)."""
    files = sorted((data / "rates").glob("fx-*.json"))
    if not files:
        raise RuntimeError("no exchange rates yet: run `rates` first")
    before = [f for f in files if f.stem[3:] <= day]
    return json.loads((before[-1] if before else files[0]).read_text())


def price_levels(data: Path) -> dict[str, dict]:
    p = data / "rates" / "price-levels.json"
    return json.loads(p.read_text())["countries"] if p.exists() else {}


def _age_days(p: Path) -> float:
    return (datetime.now(timezone.utc).timestamp() - p.stat().st_mtime) / 86400
