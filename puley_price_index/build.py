"""From raw store pages to the published index (data/latest/*) and the change log (data/history/changes.csv).

Plan names come back in English (?l=en-GB), so the same plan has the same name in every store. A page doesn't say how long a
plan lasts, so the period comes from the name when it says so ("Monthly", "12 months", "Annual"), otherwise from the prices:
when one plan name has several prices in a store, the cheapest is the monthly one and a price 7-14 times higher is the yearly
one. Inferred periods are marked in the data. Prices are converted to US dollars with the day's exchange rates.
"""

from __future__ import annotations

import csv
import io
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .apps import APPS, App
from .money import parse_price
from .rates import latest_fx, price_levels

PERIODS = [
    ("year", re.compile(r"\b(12[\s-]?months?|1[\s-]?year|one[\s-]year|yearly|annual(?:ly)?|per[\s-]year|year)\b", re.I)),
    ("half-year", re.compile(r"\b(6[\s-]?months?|six[\s-]months?|semi-?annual(?:ly)?)\b", re.I)),
    ("quarter", re.compile(r"\b(3[\s-]?months?|three[\s-]months?|quarterly)\b", re.I)),
    ("week", re.compile(r"\b(1[\s-]?week|7[\s-]?days?|weekly|week)\b", re.I)),
    ("month", re.compile(r"\b(1[\s-]?month|one[\s-]month|30[\s-]?days?|monthly|month)\b", re.I)),
    ("lifetime", re.compile(r"\b(lifetime|forever|one[\s-]time)\b", re.I)),
]
PUBLISHED = ("month", "year")
# One-off purchases sold next to the plans: credits, coin and gem packs, boosts. They aren't subscriptions, so they're left out.
CONSUMABLE = re.compile(r"\b(credits?|packs?|coins?|gems?|tokens?|charms|boosts?|super ?likes?|super ?swipes?|spotlights?|tickets?|"
                        r"bundles?|top[\s-]?ups?|lives|restores?|first impressions?)\b", re.I)
MUDDLED_MAX = 0.15  # share of stores where a plan may show conflicting prices before it's held back
PRICE_FIELDS = ["date", "app", "plan", "plan_name", "period", "period_inferred", "cc", "country", "currency", "price", "price_text",
                "usd", "usd_per_month", "vs_us_pct", "feels_like_usd"]


def plan_key(name: str) -> str:
    s = name.lower()
    for _, rx in PERIODS:
        s = rx.sub(" ", s)
    s = re.sub(r"\b(plan|subscription|membership|auto[\s-]?renew(?:al|ing)?|renewing)\b", " ", s)
    s = re.sub(r"[^\w+]+", "-", s).strip("-")
    return s or "plan"


def assign_periods(items: list[tuple[str, str, Decimal]]) -> list[dict]:
    """One store's plans -> [{name, text, price, key, period, inferred}]."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for name, text, price in items:
        explicit = next((p for p, rx in PERIODS if rx.search(name)), None)
        groups[plan_key(name)].append({"name": name, "text": text, "price": price, "explicit": explicit})
    out = []
    for key, rows in groups.items():
        rows.sort(key=lambda r: r["price"])
        base = next((r["price"] for r in rows if r["explicit"] == "month"), None)
        for r in rows:
            if r["explicit"]:
                period, inferred = r["explicit"], False
            elif base is None:
                period, inferred, base = "month", True, r["price"]
            else:
                ratio = float(r["price"] / base) if base else 0
                period = "year" if 7 <= ratio <= 14 else "half-year" if 4 <= ratio < 7 else "quarter" if 2.2 <= ratio < 4 else "variant"
                inferred = True
            out.append({"name": r["name"], "text": r["text"], "price": r["price"], "key": key, "period": period, "inferred": inferred})
    # two different prices under one name and period: keep the first (Apple lists the most bought first) and mark the rest
    seen = set()
    for r in out:
        if (r["key"], r["period"]) in seen:
            r["period"] = "variant"
        seen.add((r["key"], r["period"]))
    return out


def latest_raw(data: Path, app: App, day: str, max_age: int = 10) -> dict | None:
    best = None
    for p in sorted((data / "raw").glob(f"*/{app.slug}.json")):
        d = p.parent.name
        if d <= day and (datetime.fromisoformat(day) - datetime.fromisoformat(d)).days <= max_age:
            best = p
    return json.loads(best.read_text()) if best else None


def build(data: Path, day: str | None = None, log=print) -> dict:
    day = day or max((p.name for p in (data / "raw").iterdir() if p.is_dir()), default=None)
    if not day:
        raise RuntimeError("no raw prices yet: run `collect` first")
    fx = latest_fx(data, day)
    rates = {k.upper(): Decimal(str(v)) for k, v in fx["rates"].items()}
    levels = price_levels(data)
    countries = {c["cc"].lower(): c for c in json.loads((data / "countries.json").read_text())["countries"]}
    stores = json.loads((data / "storefronts.json").read_text())["storefronts"]
    latest = data / "latest"
    (latest / "apps").mkdir(parents=True, exist_ok=True)
    (latest / "countries").mkdir(parents=True, exist_ok=True)

    all_rows: list[dict] = []
    index_apps = []
    skipped: list[dict] = []
    per_country: dict[str, list[dict]] = defaultdict(list)
    for app in APPS:
        raw = latest_raw(data, app, day)
        if not raw:
            continue
        plans: dict[tuple[str, str], dict] = {}
        names: dict[tuple[str, str], Counter] = defaultdict(Counter)
        sold_in = 0
        per_store = []
        for cc, entry in raw["stores"].items():
            if not entry.get("sold") or not entry.get("iaps"):
                continue
            cur = (entry.get("currency") or stores.get(cc, {}).get("currency") or "").upper()
            if cur not in rates:
                continue
            parsed = [(n, t, parse_price(t, cur)) for n, t in entry["iaps"] if not CONSUMABLE.search(n)]
            parsed = [(n, t, p) for n, t, p in parsed if p and p > 0]
            if not parsed:
                continue
            sold_in += 1
            rows = assign_periods(parsed)
            sizes = Counter(r["key"] for r in rows)
            for r in rows:
                r["usd_raw"] = float(r["price"] / rates[cur])
                r["single"] = sizes[r["key"]] == 1
                r["explicit_other"] = (not r["inferred"]) and r["period"] != "month"
            per_store.append((cc, cur, rows, parsed))
        # A store that lists only one price for a plan doesn't say whether it's monthly or yearly. Compare it with the plan's
        # monthly price in the stores that show both: six times dearer is the yearly one (Character.AI+ in Croatia lists only
        # its €99.99 year).
        ref: dict[str, float] = {}
        for key in {r["key"] for _, _, rows, _p in per_store for r in rows}:
            vals = [r["usd_raw"] for _, _, rows, _p in per_store for r in rows if r["key"] == key and r["period"] == "month" and not r["single"]]
            if len(vals) >= 5:
                ref[key] = statistics.median(vals)
        # Some apps sell several price points under one plan name in the same store (old prices kept for existing
        # subscribers, offers, prices that vary by user). A store where a plan shows three or more prices, or two that
        # aren't a monthly/yearly pair, is left out for that plan; a plan that's like that in over 10% of stores isn't
        # published at all (Duolingo, Tinder and Calm on 8 Oct 2026). Better a missing country than a wrong price.
        seen_in: dict[str, int] = defaultdict(int)
        muddled: dict[str, set] = defaultdict(set)
        names_by_key: dict[str, set] = defaultdict(set)
        for cc, cur, rows, parsed in per_store:
            by_key: dict[str, set] = defaultdict(set)
            for n, _t, pr in parsed:  # the raw list, before duplicates are tidied away
                k = plan_key(n)
                names_by_key[k].add(n)
                explicit = next((per for per, rx in PERIODS if rx.search(n)), None)
                if explicit in (None, "month"):
                    by_key[k].add(float(pr))
            for key, prices in by_key.items():
                ps = sorted(prices)
                seen_in[key] += 1
                if len(ps) >= 3 or (len(ps) == 2 and not 3.5 <= ps[1] / ps[0] <= 15):
                    muddled[key].add(cc)
        clean_keys = {k for k, n in seen_in.items() if len(muddled[k]) / n <= MUDDLED_MAX}
        # the app's main plan: the one named in apps.py, else the one sold in the most stores. If that plan is muddled the
        # whole app waits; publishing a side plan in its place would mislead.
        named = [k for k in seen_in if app.headline and any(re.search(app.headline, n, re.I) for n in names_by_key[k])]
        main = max(named or seen_in, key=lambda k: seen_in[k]) if seen_in else None
        if main is None or main not in clean_keys:
            share = len(muddled[main]) / seen_in[main] if main else 1
            skipped.append({"app": app.slug, "name": app.name, "category": app.category, "main_plan": main, "muddled_share": round(share, 2),
                            "why": f"Its main plan shows several different prices in the same country in {share:.0%} of stores, so no single price can be given."})
            continue
        for cc, cur, rows, _p in per_store:
            rows[:] = [r for r in rows if r["key"] in clean_keys and cc not in muddled[r["key"]]]
            for r in rows:
                if r["single"] and r["inferred"] and r["period"] == "month" and r["key"] in ref:
                    m = r["usd_raw"] / ref[r["key"]]
                    r["period"] = "year" if m >= 6 else "variant" if m <= 1 / 6 else "month"
            for r in rows:
                if r["period"] not in PUBLISHED:
                    continue
                k = (r["key"], r["period"])
                names[k][r["name"]] += 1
                usd = r["price"] / rates[cur]
                lvl = levels.get(cc.upper(), {}).get("ratio")
                plans.setdefault(k, {"rows": []})["rows"].append({
                    "cc": cc.upper(), "country": countries.get(cc, {}).get("name", cc.upper()),
                    "region": countries.get(cc, {}).get("region"), "income": countries.get(cc, {}).get("income"),
                    "currency": cur, "price": float(r["price"]), "price_text": r["text"], "usd": round(float(usd), 2),
                    "usd_per_month": round(float(usd) / (12 if r["period"] == "year" else 1), 2),
                    "feels_like_usd": round(float(usd) / lvl, 2) if lvl else None, "period_inferred": r["inferred"]})
        if not plans:
            skipped.append({"app": app.slug, "name": app.name, "category": app.category, "why": "No plan has a single clear price."})
            continue
        out_plans = []
        for (key, period), p in plans.items():
            rows = sorted(p["rows"], key=lambda x: x["usd"])
            us = next((x["usd"] for x in rows if x["cc"] == "US"), None)
            ref = us or statistics.median(x["usd"] for x in rows)
            for i, x in enumerate(rows, 1):
                x["rank"] = i
                x["vs_us_pct"] = round((x["usd"] / ref - 1) * 100, 1) if ref else None
            usds = [x["usd"] for x in rows]
            label = names[(key, period)].most_common(1)[0][0]
            out_plans.append({
                "key": key, "name": label, "period": period, "stores": len(rows),
                "stats": {"us": us, "min": usds[0], "max": usds[-1], "median": round(statistics.median(usds), 2),
                          "spread": round(usds[-1] / usds[0], 2) if usds[0] else None,
                          "cheapest": [{"cc": x["cc"], "country": x["country"], "usd": x["usd"]} for x in rows[:5]],
                          "priciest": [{"cc": x["cc"], "country": x["country"], "usd": x["usd"]} for x in rows[::-1][:5]]},
                "rows": rows})
        monthly = [p for p in out_plans if p["period"] == "month"]
        pick = [p for p in monthly if app.headline and re.search(app.headline, p["name"], re.I)] or monthly or out_plans
        head = max(pick, key=lambda p: (p["stores"], -p["stats"]["median"]))
        out_plans.sort(key=lambda p: (p is not head, p["period"] != "month", -p["stores"], p["stats"]["median"]))
        not_sold = sorted(({"cc": cc.upper(), "country": countries.get(cc, {}).get("name", cc.upper())}
                           for cc, e in raw["stores"].items() if e.get("sold") is False), key=lambda x: x["country"])
        doc = {"app": app.slug, "name": app.name, "category": app.category, "app_store_id": app.id, "collected": raw["date"],
               "fx_date": fx["date"], "sold_in": sold_in, "stores_read": len(raw["stores"]), "not_sold": not_sold,
               "headline": {"key": head["key"], "period": head["period"]}, "plans": out_plans}
        (latest / "apps" / f"{app.slug}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        index_apps.append({"app": app.slug, "name": app.name, "category": app.category, "collected": raw["date"], "sold_in": sold_in,
                           "plans": len(out_plans), "headline": {k: head[k] for k in ("key", "name", "period", "stores")} | {"stats": head["stats"]}})
        for p in out_plans:
            for x in p["rows"]:
                all_rows.append({"date": raw["date"], "app": app.slug, "plan": p["key"], "plan_name": p["name"], "period": p["period"],
                                 **{f: x.get(f) for f in PRICE_FIELDS if f in x}})
                if p is head:
                    per_country[x["cc"]].append({"app": app.slug, "name": app.name, "category": app.category, "plan": p["name"],
                                                 **{f: x[f] for f in ("currency", "price", "price_text", "usd", "vs_us_pct", "feels_like_usd", "rank")},
                                                 "of": p["stores"]})
    if not index_apps:
        raise RuntimeError("nothing to publish")

    for stale in (latest / "apps").glob("*.json"):
        if stale.stem not in {a["app"] for a in index_apps}:
            stale.unlink()  # a held-back app's old published file (regenerated every build from data/raw)
    country_index = []
    for cc, items in sorted(per_country.items()):
        c = countries.get(cc.lower(), {})
        vs = [i["vs_us_pct"] for i in items if i["vs_us_pct"] is not None]
        doc = {"cc": cc, "name": c.get("name", cc), "region": c.get("region"), "income": c.get("income"),
               "currency": stores.get(cc.lower(), {}).get("currency"), "price_level": levels.get(cc, {}).get("ratio"),
               "fx_date": fx["date"], "apps": sorted(items, key=lambda i: i["name"].lower())}
        (latest / "countries" / f"{cc.lower()}.json").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
        country_index.append({"cc": cc, "name": doc["name"], "region": doc["region"], "income": doc["income"], "currency": doc["currency"],
                              "apps": len(items), "median_vs_us_pct": round(statistics.median(vs), 1) if vs else None})

    changes = _log_changes(data, all_rows, log)
    with (latest / "prices.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=PRICE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(all_rows, key=lambda r: (r["app"], r["plan"], r["period"], r["cc"])))
    index = {"name": "Puley Price Index", "url": "https://puley.com/prices", "updated": day, "fx_date": fx["date"],
             "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "stores": len(stores), "apps": index_apps,
             "countries": country_index, "changes_logged": changes, "held_back": skipped,
             "sources": {"prices": "Apple App Store app pages (apps.apple.com), In-App Purchases list, one page per app per country",
                         "fx": fx.get("source"), "price_levels": "World Bank PA.NUS.PPPC.RF (CC BY 4.0)"},
             "license": "Data: CC BY 4.0, credit \"Puley Price Index (puley.com/prices)\" with a link. Code: MIT."}
    (latest / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1))
    _readme(data.parent / "README.md", index, len(all_rows))
    _archive(data, day)
    log(f"built {day}: {len(index_apps)} apps, {len(country_index)} countries, {len(all_rows)} prices, {changes} changes logged")
    return index


def _flag(cc: str) -> str:
    return "".join(chr(0x1F1A5 + ord(c)) for c in cc.upper()) if len(cc) == 2 else ""


def _readme(path: Path, index: dict, n_prices: int) -> None:
    """Refresh the table between the index markers in the README with today's numbers."""
    if not path.exists():
        return
    text = path.read_text()
    a, b = "<!-- index:start -->", "<!-- index:end -->"
    if a not in text or b not in text:
        return
    money = lambda v: "–" if v is None else f"${v:,.2f}"
    rows = ["| App | Main plan | In the US | Cheapest | Dearest | Countries |", "| --- | --- | ---: | --- | --- | ---: |"]
    for x in sorted(index["apps"], key=lambda x: (x["category"] != "AI assistants", x["name"].lower())):
        h, st = x["headline"], x["headline"]["stats"]
        if h["stores"] < 10:
            continue
        lo, hi = st["cheapest"][0], st["priciest"][0]
        rows.append(f"| [{x['name']}](https://puley.com/prices/{x['app']}) | {h['name']} | {money(st['us'])} | "
                    f"{_flag(lo['cc'])} {lo['country']} {money(lo['usd'])} | {_flag(hi['cc'])} {hi['country']} {money(hi['usd'])} | {h['stores']} |")
    body = (f"\n**Updated {index['updated']}** · {n_prices:,} prices · {len(rows) - 2} apps · {index['stores']} countries · "
            f"US dollars at {index['fx_date']} exchange rates\n\n" + "\n".join(rows) + "\n")
    i, j = text.index(a) + len(a), text.index(b)
    path.write_text(text[:i] + body + text[j:])


def _log_changes(data: Path, rows: list[dict], log) -> int:
    """Compare with the previous data/latest/prices.csv and append every local-price change to data/history/changes.csv."""
    prev_path = data / "latest" / "prices.csv"
    hist = data / "history" / "changes.csv"
    hist.parent.mkdir(parents=True, exist_ok=True)
    if not prev_path.exists():
        return 0
    prev = {(r["app"], r["plan"], r["period"], r["cc"]): r for r in csv.DictReader(prev_path.open())}
    new = []
    for r in rows:
        p = prev.get((r["app"], r["plan"], r["period"], r["cc"]))
        if p and p["currency"] == r["currency"] and abs(float(p["price"]) - r["price"]) > 1e-9 and p["date"] < r["date"]:
            new.append({"date": r["date"], "app": r["app"], "plan": r["plan_name"], "period": r["period"], "cc": r["cc"], "country": r["country"],
                        "currency": r["currency"], "old_price": p["price"], "new_price": r["price"],
                        "change_pct": round((r["price"] / float(p["price"]) - 1) * 100, 1)})
    if new:
        exists = hist.exists()
        with hist.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(new[0]))
            if not exists:
                w.writeheader()
            w.writerows(new)
    return len(new)


def _archive(data: Path, day: str) -> None:
    """Pack the day's raw store pages (data/raw/<day>/*.json, working files) into data/archive/<year>/<day>.json.gz for the record."""
    import gzip
    src = data / "raw" / day
    if not src.is_dir():
        return
    out = data / "archive" / day[:4] / f"{day}.json.gz"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {p.stem: json.loads(p.read_text()) for p in sorted(src.glob("*.json"))}
    with gzip.open(out, "wt", encoding="utf-8") as f:
        json.dump({"date": day, "apps": doc}, f, ensure_ascii=False, separators=(",", ":"))
