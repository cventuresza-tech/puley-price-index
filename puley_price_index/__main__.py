"""python -m puley_price_index <command>

  discover                 find every App Store country and its currency (data/storefronts.json)
  collect [--all] [slugs] [--workers N]
                           read today's prices (daily apps; --all for every app; or name apps). With an engine
                           (PULEY_ENGINE_URL + PULEY_ENGINE_TOKEN) N apps are read at once; directly, one request at a time
  rates                    today's exchange rates and the World Bank price levels
  build [--date D]         turn raw prices into data/latest/* and the history files
  daily                    what the server runs once a day: collect (weekly apps on their weekday), rates, build
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import apps as A
from .collect import collect_app, today
from .fetch import Fetcher  # noqa: F401

DATA = Path(__file__).resolve().parents[1] / "data"


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} {msg}", flush=True)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    if cmd == "discover":
        from .storefronts import discover
        countries = {c["cc"].lower(): c["name"] for c in json.loads((DATA / "countries.json").read_text())["countries"]}
        f = Fetcher(log=log)
        stores = discover(countries, f, log=log)
        (DATA / "storefronts.json").write_text(json.dumps({"checked": today(), "count": len(stores), "storefronts": stores},
                                                          ensure_ascii=False, indent=1, sort_keys=True))
        log(f"{len(stores)} App Store countries; {f.requests} requests, {f.throttled} throttled")
        return 0
    if cmd in ("collect", "daily"):
        from .storefronts import load
        stores = load(DATA / "storefronts.json")
        if cmd == "daily":
            weekday = datetime.now(timezone.utc).weekday()
            chosen = [a for i, a in enumerate(A.APPS) if a.daily or i % 7 == weekday]
        elif "--all" in rest:
            chosen = list(A.APPS)
        else:
            names = [r for i, r in enumerate(rest) if not r.startswith("-") and (i == 0 or rest[i - 1] != "--workers")]
            chosen = [A.BY_SLUG[n] for n in names] if names else [a for a in A.APPS if a.daily]
        from concurrent.futures import ThreadPoolExecutor
        from .fetch import EngineFetcher, make_fetcher
        workers = int(rest[rest.index("--workers") + 1]) if "--workers" in rest else 1
        probe = make_fetcher(log=log)
        if not isinstance(probe, EngineFetcher):
            workers = 1  # reading Apple directly: one request at a time, from one place
        log(f"reading {len(chosen)} apps in {len(stores)} stores {'through ' + probe.base if isinstance(probe, EngineFetcher) else 'directly'}, "
            f"{workers} at a time")

        def run(app):
            f = make_fetcher(log=lambda m: log(f"[{app.slug}] {m}"))
            collect_app(app, stores, DATA, f, log=log)
            return f.requests, f.throttled

        with ThreadPoolExecutor(max_workers=workers) as pool:
            done = list(pool.map(run, chosen))
        log(f"collected {len(chosen)} apps; {sum(d[0] for d in done)} requests, {sum(d[1] for d in done)} retried")
        if cmd == "collect":
            return 0
    if cmd in ("rates", "daily"):
        from .rates import fetch_rates
        fetch_rates(DATA, log=log)
        if cmd == "rates":
            return 0
    if cmd in ("build", "daily"):
        from .build import build
        day = rest[rest.index("--date") + 1] if "--date" in rest else None
        build(DATA, day=day, log=log)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
