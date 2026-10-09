"""A polite fetcher for apps.apple.com: one request at a time, a few seconds apart, slower after any 429. Standard library only.

apps.apple.com/robots.txt allows app pages (it disallows /api/, /v1/, /WebObjects/, /includes/ and search). Apple answers
bursts with 429, so the pace adapts: it starts at `delay` seconds, backs off on 429 (honouring Retry-After), and speeds up
again slowly after a run of clean answers. The user agent names the project and where to read about it.
"""

from __future__ import annotations

import gzip
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "PuleyPriceIndex/1.0 (+https://puley.com/prices/about)"


@dataclass
class Response:
    status_code: int
    url: str
    text: str
    headers: dict = field(default_factory=dict)

    def json(self):
        return json.loads(self.text)


def http_get(url: str, params: dict | None = None, timeout: float = 40.0, headers: dict | None = None) -> Response:
    """GET with gzip and redirects; HTTP errors come back as a Response, network errors raise OSError."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"user-agent": USER_AGENT, "accept-encoding": "gzip", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body, status, final, hdrs = r.read(), r.status, r.geturl(), dict(r.headers)
    except urllib.error.HTTPError as e:
        body, status, final, hdrs = e.read() or b"", e.code, url, dict(e.headers or {})
    if hdrs.get("Content-Encoding", hdrs.get("content-encoding", "")) == "gzip":
        body = gzip.decompress(body)
    return Response(status, final, body.decode("utf-8", "replace"), {k.lower(): v for k, v in hdrs.items()})


class Fetcher:
    def __init__(self, delay: float = 4.0, min_delay: float = 3.0, max_delay: float = 30.0, timeout: float = 40.0, log=print):
        self.delay, self.min_delay, self.max_delay, self.timeout = delay, min_delay, max_delay, timeout
        self.log = log
        self.clean = 0
        self.requests = 0
        self.throttled = 0
        self._last = 0.0
        self.headers = {"accept": "text/html,application/xhtml+xml", "accept-language": "en-GB,en;q=0.9"}

    def _wait(self) -> None:
        gap = self.delay * random.uniform(0.85, 1.25) - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)

    def get(self, url: str, tries: int = 5) -> Response | None:
        """The page, or None if it doesn't exist (404). Raises RuntimeError after `tries` throttled or failed attempts."""
        for attempt in range(1, tries + 1):
            self._wait()
            self._last = time.monotonic()
            self.requests += 1
            try:
                r = http_get(url, timeout=self.timeout, headers=self.headers)
            except OSError as e:
                self.log(f"  network error ({e.__class__.__name__}), retry {attempt}/{tries}")
                time.sleep(min(60, 5 * attempt))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                self.throttled += r.status_code == 429
                self.clean = 0
                self.delay = min(self.max_delay, self.delay * 1.6)
                wait = _retry_after(r) or min(300, 30 * attempt)
                self.log(f"  {r.status_code} from Apple: waiting {wait:.0f}s, pace now {self.delay:.1f}s")
                time.sleep(wait)
                continue
            self.clean += 1
            if self.clean % 40 == 0:
                self.delay = max(self.min_delay, self.delay * 0.9)
            if r.status_code == 404:
                return None
            if r.status_code >= 400:
                raise RuntimeError(f"{r.status_code} for {url}")
            return r
        raise RuntimeError(f"gave up on {url} after {tries} tries")

    def close(self) -> None:
        pass


class EngineFetcher:
    """Reads pages through a web-reading engine with Skryp's API (POST /v1/scrape, raw HTML). Puley's daily run uses
    Skryp (https://skryp.dev); without an engine, Fetcher reads apps.apple.com directly at a polite pace.

    Reads go out directly first and wait out Apple's 429s; only a page still throttled after `direct_tries` goes out
    through the paid residential network. Measured 9 Oct 2026: 36 of 45 direct reads 1.5 s apart answered, and an
    App Store page is ~63 KB on the wire, so forcing every read through residential paid for traffic it did not need."""

    def __init__(self, base: str, token: str, delay: float | None = None, network: str | None = None, log=print):
        self.base, self.token, self.log = base.rstrip("/"), token, log
        self.delay = delay if delay is not None else float(os.environ.get("PULEY_ENGINE_DELAY", "2.0"))
        self.network = network or os.environ.get("PULEY_ENGINE_NETWORK", "direct")
        self.fallback = os.environ.get("PULEY_ENGINE_FALLBACK", "residential")  # "" never pays for residential
        self.direct_tries = int(os.environ.get("PULEY_ENGINE_DIRECT_TRIES", "3"))
        self.requests = self.throttled = self.fallbacks = 0
        self._last = 0.0

    def get(self, url: str, tries: int = 6) -> Response | None:
        for attempt in range(1, tries + 1):
            network = self.fallback if (self.fallback and attempt > self.direct_tries) else self.network
            gap = self.delay - (time.monotonic() - self._last)
            if gap > 0:
                time.sleep(gap)
            self._last = time.monotonic()
            self.requests += 1
            body = json.dumps({"url": url, "formats": ["raw_html"], "main_content": False, "render": "never", "max_age_s": 0,
                               "network": network}).encode()
            req = urllib.request.Request(self.base + "/v1/scrape", data=body, method="POST", headers={
                "authorization": f"Bearer {self.token}", "content-type": "application/json", "user-agent": USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=150) as r:
                    d = json.loads(r.read())
            except urllib.error.HTTPError as e:
                d = {"error": f"engine {e.code}: {(e.read() or b'')[:200].decode('utf-8', 'replace')}"}
            except OSError as e:
                d = {"error": f"network: {e.__class__.__name__}"}
            html = d.get("raw_html") or ""
            status = (d.get("metadata") or {}).get("status_code") or d.get("status_code")
            if status == 404 or re.search(r"\b404\b|not found", str(d.get("error") or ""), re.I):
                return None
            if html and "serialized-server-data" in html:
                self.fallbacks += network != self.network
                return Response(200, (d.get("metadata") or {}).get("url") or url, html)
            self.throttled += 1
            err = str(d.get("error") or "no page")
            if attempt > 2:
                self.log(f"  engine: {err[:120]} (try {attempt}/{tries}, {network})")
            if network == self.network and network != self.fallback:
                time.sleep(min(30, 4 * 2 ** (attempt - 1)))  # direct: wait out Apple's rate window (4, 8, 16 s)
            else:
                time.sleep(3 if "429" in err else min(60, 10 * attempt))  # a 429 on one exit: the next try goes out through another
        raise RuntimeError(f"engine gave up on {url}")

    def close(self) -> None:
        pass


def _retry_after(r: Response) -> float | None:
    v = r.headers.get("retry-after")
    try:
        return float(v) if v else None
    except ValueError:
        return None


import urllib.parse  # noqa: E402  (used by http_get)


def make_fetcher(log=print):
    """An engine fetcher when PULEY_ENGINE_URL and PULEY_ENGINE_TOKEN (or Puley's INFRARED_ENGINE settings) are set,
    otherwise the direct, polite fetcher."""
    base = os.environ.get("PULEY_ENGINE_URL") or os.environ.get("INFRARED_ENGINE")
    token = os.environ.get("PULEY_ENGINE_TOKEN") or os.environ.get("INFRARED_ENGINE_TOKEN")
    return EngineFetcher(base, token, log=log) if base and token else Fetcher(log=log)
