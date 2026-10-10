"""Coinbase Exchange's public market data: the one module that speaks to it.

REST at api.exchange.coinbase.com: `/products`, `/currencies`,
`/products/{id}/candles`, `/products/{id}/ticker` and
`/products/{id}/book?level=1`. No key: nothing here holds a credential, and
nothing is sent but the request. The standard library's HTTP client; the
plugin depends on nothing but the SDK.

**Rate limits, honoured.** Coinbase allows public REST 10 requests a second
per IP, in bursts to 15; this client spends at most half that from a token
bucket, and a 429 is waited out (its Retry-After, else 1, 2, 4 seconds) and
asked again at most three times, each one counted.

**Every response is a raw record first** (raw.py), kept exactly as its bytes
arrived, with its status and the headers that say how fresh it is
(Coinbase's REST sits behind a CDN cache: `cache-control`, `age`,
`cf-cache-status`), before anything is read from it. A body is parsed with
`json_decimal`, so Coinbase's candles, which are JSON numbers, become
Decimals from their own text and never a float.

**Where it answers from.** Coinbase itself; or, in synthetic mode, the
synthetic exchanges this package carries, or a developer's recorded ones,
through the same requests (synthetic.py).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from .market import Health, json_decimal
from .raw import RawStore

REST = "https://api.exchange.coinbase.com"
USER_AGENT = "meridian-coinbase (+https://open-meridian.dev)"

#: Half of Coinbase's public allowance: 10 a second, bursts to 15.
RATE_PER_SECOND = 5.0
BURST = 5
#: Coinbase's most candles in one request.
MOST_CANDLES = 300
#: The headers kept with a record: freshness and rate limits.
KEPT_HEADERS = ("date", "cache-control", "age", "cf-cache-status", "etag", "retry-after")


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes


Transport = Callable[[str, Mapping[str, str]], Response]


def urllib_transport(url: str, headers: Mapping[str, str]) -> Response:
    """One GET over HTTPS, with the standard library."""
    request = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=15) as answer:
            return Response(
                answer.status, {k.lower(): v for k, v in answer.headers.items()}, answer.read()
            )
    except urllib.error.HTTPError as answer:
        return Response(
            answer.code, {k.lower(): v for k, v in answer.headers.items()}, answer.read()
        )


class RateLimiter:
    """A token bucket: `rate` calls a second, `burst` at once."""

    def __init__(
        self,
        rate: float,
        burst: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rate, self.burst = rate, burst
        self._clock, self._sleep = clock, sleep
        self._tokens = float(burst)
        self._at = clock()
        self.waited = 0.0

    def acquire(self) -> None:
        now = self._clock()
        self._tokens = min(self.burst, self._tokens + (now - self._at) * self.rate)
        self._at = now
        if self._tokens < 1:
            wait = (1 - self._tokens) / self.rate
            self._sleep(wait)
            self.waited += wait
            self._at = self._clock()
            self._tokens = 1.0
        self._tokens -= 1


class VenueError(Exception):
    """Coinbase answered with something other than what was asked for, or did
    not answer."""

    def __init__(self, call: str, status: int, detail: str, raw_key: str = "") -> None:
        kept = f" (raw record {raw_key})" if raw_key else ""
        super().__init__(f"Coinbase's {call}: {status or 'no answer'} {detail}{kept}")
        self.call, self.status, self.detail, self.raw_key = call, status, detail, raw_key


@dataclass(frozen=True)
class Fetched:
    """A parsed body, the key of the raw record it was kept as, and when it
    arrived."""

    value: Any
    raw_key: str
    received_at_ns: int


class Coinbase:
    """Coinbase Exchange's public REST, every response kept."""

    def __init__(
        self,
        store: RawStore,
        transport: Transport = urllib_transport,
        limiter: RateLimiter | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
        sleep: Callable[[float], None] = time.sleep,
        retries: int = 3,
    ) -> None:
        self.store, self.transport = store, transport
        self.limiter = limiter or RateLimiter(RATE_PER_SECOND, BURST)
        self.clock_ns, self.sleep, self.retries = clock_ns, sleep, retries
        self.health = Health()

    def _get(
        self,
        call: str,
        name: str,
        path: str,
        params: Mapping[str, str] | None = None,
        live: bool = False,
    ) -> Fetched:
        url = REST + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        for attempt in range(self.retries + 1):
            self.limiter.acquire()
            self.health.waited_seconds = self.limiter.waited
            self.health.calls += 1
            try:
                answer = self.transport(url, headers)
            except OSError as failed:
                self._failed(f"{call}: {failed}")
                raise VenueError(call, 0, str(failed)) from None
            received = self.clock_ns()
            text = answer.body.decode("utf-8", errors="replace")
            record = {
                "venue": "coinbase",
                "call": call,
                "request": {"method": "GET", "url": url},
                "received_at_ns": received,
                "status": answer.status,
                "headers": {h: answer.headers[h] for h in KEPT_HEADERS if h in answer.headers},
                "body": text,
            }
            ok = answer.status == 200
            if live and ok:
                raw_key = self.store.keep_line(call, name, record)
            else:
                raw_key = self.store.keep(call, name, record)
            if answer.status == 429 and attempt < self.retries:
                self.health.rate_limited += 1
                retry_after = answer.headers.get("retry-after", "")
                self.sleep(float(retry_after) if retry_after.isdigit() else 2.0**attempt)
                continue
            if not ok:
                self._failed(f"{call}: {answer.status} {_message(text)}")
                raise VenueError(call, answer.status, _message(text), raw_key)
            try:
                value = json_decimal(text)
            except json.JSONDecodeError as broken:
                self._failed(f"{call}: not JSON")
                raise VenueError(call, answer.status, f"not JSON: {broken}", raw_key) from None
            self.health.last_ok_ns = received
            return Fetched(value, raw_key, received)
        raise AssertionError("unreachable")

    def _failed(self, why: str) -> None:
        self.health.failures += 1
        self.health.last_failed_ns = self.clock_ns()
        self.health.last_error = why

    def products(self) -> Fetched:
        return self._get("products", "products", "/products")

    def currencies(self) -> Fetched:
        return self._get("currencies", "currencies", "/currencies")

    def candles(self, product: str, start_s: int, end_s: int) -> Fetched:
        """Daily candles from `start_s` to `end_s` (UTC seconds), at most 300."""
        if (end_s - start_s) // 86_400 > MOST_CANDLES:
            raise ValueError(f"Coinbase gives at most {MOST_CANDLES} candles a request")
        return self._get(
            "candles",
            product,
            f"/products/{urllib.parse.quote(product)}/candles",
            {"granularity": "86400", "start": _iso(start_s), "end": _iso(end_s)},
        )

    def ticker(self, product: str) -> Fetched:
        return self._get(
            "ticker", product, f"/products/{urllib.parse.quote(product)}/ticker", live=True
        )

    def book(self, product: str) -> Fetched:
        """The best bid and offer, with their sizes (level 1)."""
        return self._get(
            "book",
            product,
            f"/products/{urllib.parse.quote(product)}/book",
            {"level": "1"},
            live=True,
        )


def _message(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text[:200]
    if isinstance(parsed, dict) and "message" in parsed:
        return str(parsed["message"])[:200]
    return text[:200]


def _iso(at_s: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at_s))
