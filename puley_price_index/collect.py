"""Collecting one day's prices: every tracked app in every store, saved as it goes so a stopped run picks up where it left off.

Raw results land in data/raw/<date>/<app>.json: for each store, the store's currency, the plan names and prices exactly as
Apple printed them, the time, and whether the app is sold there at all.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .apps import App
from .fetch import Fetcher
from .parse import PageError, parse_app_page


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def raw_path(data: Path, day: str, app: App) -> Path:
    return data / "raw" / day / f"{app.slug}.json"


def collect_app(app: App, stores: dict[str, dict], data: Path, fetcher: Fetcher, day: str | None = None, log=print) -> dict:
    day = day or today()
    path = raw_path(data, day, app)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(path.read_text()) if path.exists() else {"app": app.slug, "id": app.id, "date": day, "stores": {}}
    todo = [cc for cc in sorted(stores) if cc not in doc["stores"] or "error" in doc["stores"][cc]]  # failed reads get another go
    if todo:
        log(f"{app.name}: {len(todo)} stores to read ({len(doc['stores'])} already done)")
    for n, cc in enumerate(todo, 1):
        url = f"https://apps.apple.com/{cc}/app/id{app.id}?l=en-GB"
        entry: dict = {"t": int(time.time())}
        try:
            r = fetcher.get(url)
            if r is None:
                entry["sold"] = False  # the app isn't in this store
            else:
                page = parse_app_page(r.text)
                entry.update(sold=True, currency=page.currency or stores[cc].get("currency"), iaps=page.iaps)
                if page.currency and page.currency != stores[cc].get("currency"):
                    entry["store_currency"] = stores[cc].get("currency")
        except (RuntimeError, PageError) as e:
            entry["error"] = str(e)[:200]
        doc["stores"][cc] = entry
        if n % 10 == 0 or n == len(todo):
            _save(path, doc)
    _save(path, doc)
    return doc


def _save(path: Path, doc: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    tmp.replace(path)
