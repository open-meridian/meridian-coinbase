"""Coinbase Exchange's public market data: the one module that speaks to it.

REST at api.exchange.coinbase.com (`/products`, `/currencies`,
`/products/{id}/candles`, `/ticker`, `/book?level=1`, `/trades`, `/time`) and
the WebSocket feed at ws-feed.exchange.coinbase.com (`ticker` and `matches`,
unauthenticated). No key: nothing here holds a credential.

**Rate limits, honoured.** Coinbase allows public REST 10 requests a second
per IP, in bursts to 15; this client spends at most half that from a token
bucket, and a 429 is waited out (its Retry-After, else 1, 2, 4 seconds) and
asked again at most three times, each one counted. A WebSocket that drops is
reconnected after a growing pause, a few times at most.

**Every response is a raw record first.** Each body is kept exactly as its
bytes arrived, with its status, the headers that say how fresh it is
(Coinbase's REST sits behind a CDN cache: `cache-control`, `age`,
`cf-cache-status`) and its pagination cursors, before anything is converted
(raw.py). A body is parsed with `json_decimal`, so Coinbase's candles, which
are JSON numbers, become Decimals from their own text and never a float.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Protocol

from .raw import RawStore
from .rows import NANOS_PER_SECOND, json_decimal

REST = "https://api.exchange.coinbase.com"
WEBSOCKET = "wss://ws-feed.exchange.coinbase.com"
USER_AGENT = "meridian-coinbase/0.1.0 (+https://open-meridian.dev)"

#: Half of Coinbase's public allowance: 10 a second, bursts to 15.
RATE_PER_SECOND = 5.0
BURST = 5
#: Coinbase's most candles in one request.
MAX_CANDLES = 300
#: The headers kept with a record: freshness, cursors, rate limits.
KEPT_HEADERS = (
    "date",
    "cache-control",
    "age",
    "cf-cache-status",
    "etag",
    "cb-before",
    "cb-after",
    "retry-after",
    "content-type",
)


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
    """Coinbase answered with something other than what was asked for."""

    def __init__(self, call: str, status: int, detail: str, raw_key: str) -> None:
        super().__init__(f"{call}: {status} {detail} (raw record {raw_key})")
        self.call, self.status, self.detail, self.raw_key = call, status, detail, raw_key


@dataclass(frozen=True)
class Fetched:
    """A parsed body, the key of the raw record it was kept as, and when it
    arrived."""

    value: Any
    raw_key: str
    received_at_ns: int


class WebSocket(Protocol):
    async def send(self, message: str) -> None: ...
    async def recv(self) -> str | bytes: ...


Connector = Callable[[str], AbstractAsyncContextManager[WebSocket]]


def websockets_connector(url: str) -> AbstractAsyncContextManager[WebSocket]:
    from websockets.asyncio.client import connect

    return connect(url, open_timeout=10, max_size=2**22, user_agent_header=USER_AGENT)


class Coinbase:
    """Coinbase Exchange's public market data, every response kept."""

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
        self.calls = 0
        self.rate_limited = 0
        self.reconnected = 0
        self._kept = 0

    def _keep(self, key: str, record: dict[str, Any]) -> str:
        self._kept += 1
        return self.store.keep(f"{key}/{record['received_at_ns']}-{self._kept}", record)

    def _get(
        self, call: str, key: str, path: str, params: Mapping[str, str] | None = None
    ) -> Fetched:
        url = REST + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        for attempt in range(self.retries + 1):
            self.limiter.acquire()
            self.calls += 1
            answer = self.transport(url, headers)
            received = self.clock_ns()
            text = answer.body.decode("utf-8", errors="replace")
            raw_key = self._keep(
                key,
                {
                    "venue": "coinbase",
                    "call": call,
                    "request": {"method": "GET", "url": url},
                    "received_at_ns": received,
                    "status": answer.status,
                    "headers": {h: answer.headers[h] for h in KEPT_HEADERS if h in answer.headers},
                    "body": text,
                },
            )
            if answer.status == 429 and attempt < self.retries:
                self.rate_limited += 1
                retry_after = answer.headers.get("retry-after", "")
                self.sleep(float(retry_after) if retry_after.isdigit() else 2.0**attempt)
                continue
            if answer.status != 200:
                raise VenueError(call, answer.status, _message(text), raw_key)
            try:
                return Fetched(json_decimal(text), raw_key, received)
            except json.JSONDecodeError as broken:
                raise VenueError(call, answer.status, f"not JSON: {broken}", raw_key) from None
        raise AssertionError("unreachable")

    def time(self) -> Fetched:
        return self._get("time", "time", "/time")

    def products(self) -> Fetched:
        return self._get("products", "products", "/products")

    def currencies(self) -> Fetched:
        return self._get("currencies", "currencies", "/currencies")

    def candles(self, product: str, granularity: int, start_ns: int, end_ns: int) -> Fetched:
        """Candles from `start_ns` to `end_ns`, at most 300 of them."""
        if (end_ns - start_ns) // (granularity * NANOS_PER_SECOND) > MAX_CANDLES:
            raise ValueError(f"Coinbase gives at most {MAX_CANDLES} candles a request")
        return self._get(
            "candles",
            f"candles/{product}/{granularity}",
            f"/products/{urllib.parse.quote(product)}/candles",
            {
                "granularity": str(granularity),
                "start": _iso(start_ns),
                "end": _iso(end_ns),
            },
        )

    def ticker(self, product: str) -> Fetched:
        return self._get(
            "ticker", f"ticker/{product}", f"/products/{urllib.parse.quote(product)}/ticker"
        )

    def book(self, product: str) -> Fetched:
        """The best bid and offer, with their sizes (level 1)."""
        return self._get(
            "book",
            f"book/{product}",
            f"/products/{urllib.parse.quote(product)}/book",
            {"level": "1"},
        )

    def trades(self, product: str, limit: int = 100) -> Fetched:
        return self._get(
            "trades",
            f"trades/{product}",
            f"/products/{urllib.parse.quote(product)}/trades",
            {"limit": str(limit)},
        )

    async def stream(
        self,
        products: Iterable[str],
        seconds: float,
        channels: Iterable[str] = ("ticker", "matches"),
        connector: Connector = websockets_connector,
        reconnects: int = 3,
        pause: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> AsyncIterator[tuple[Any, str, int]]:
        """The feed's messages for `seconds`: each parsed, kept as the next line
        of this stream's raw record, and yielded with its reference key and
        when it arrived. A dropped connection is opened again, after 1, 2, 4
        seconds, at most `reconnects` times."""
        subscribe = json.dumps(
            {
                "type": "subscribe",
                "product_ids": list(products),
                "channels": list(channels),
            }
        )
        started = self.clock_ns()
        key = f"stream/{started}"
        deadline = time.monotonic() + seconds
        attempt = 0
        while time.monotonic() < deadline:
            try:
                async with connector(WEBSOCKET) as socket:
                    await socket.send(subscribe)
                    while (left := deadline - time.monotonic()) > 0:
                        try:
                            text = await asyncio.wait_for(socket.recv(), timeout=left)
                        except TimeoutError:
                            return
                        received = self.clock_ns()
                        if isinstance(text, bytes):
                            text = text.decode("utf-8")
                        index = self.store.append(key, {"received_at_ns": received, "text": text})
                        yield json_decimal(text), f"{key}#{index}", received
                    return
            except Exception as dropped:
                if not _closed(dropped) or attempt >= reconnects:
                    raise
            await pause(2.0**attempt)
            attempt += 1
            self.reconnected += 1


def _closed(error: BaseException) -> bool:
    """A connection that dropped, which is worth opening again."""
    closed = type(error).__name__ in {"ConnectionClosed", "ConnectionClosedError"}
    return closed or isinstance(error, OSError | ConnectionError)


def _message(text: str) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text[:200]
    if isinstance(parsed, dict) and "message" in parsed:
        return str(parsed["message"])
    return text[:200]


def _iso(at_ns: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at_ns // NANOS_PER_SECOND))
