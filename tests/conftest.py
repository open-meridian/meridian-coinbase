"""Coinbase's synthetic exchanges, and the adapter the shared conformance suite
runs against.

tests/exchanges/ holds bodies shaped exactly as Coinbase Exchange documents and
sends them (checked against its public endpoints on 2026-10-03), with
invented values: candles are JSON numbers, as Coinbase sends them, and every
other figure a string. TKN and PLY are invented tokens, their contract
addresses invented. Real recordings are never committed (the plan's Q11):
`make live` writes them under recordings/, which git ignores.

`Replay` answers the client's requests from those files, through the client's
real request, raw-record and parsing path; `Adapter` is what
tests/test_conformance.py, the same file in meridian-kraken, asks for: the
suite's stage 3 expectations, held against this plugin's stage 1 and 2
exchanges (spec/vendor-differences-have-a-place-in-the-contract,
"Conformance and coverage").
"""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

import pytest

from coinbase import convert, rows
from coinbase.raw import RawStore
from coinbase.rows import Bar, DatasetDeclaration, Price, Product, Quote, RawRecordRef, Row, Trade
from coinbase.sample import Session
from coinbase.venue import Coinbase, RateLimiter, Response

EXCHANGES = Path(__file__).parent / "exchanges"
#: The synthetic exchanges' now: 2026-10-03T12:00:00Z, the day still forming.
NOW_NS = 1_791_028_800 * 1_000_000_000

#: One clock for the whole run, so no two raw records share a key.
TICKS = itertools.count(NOW_NS, 1_000)

ROUTES = {
    "/products": "products.json",
    "/currencies": "currencies.json",
    "/candles": "candles-daily.json",
    "/ticker": "ticker.json",
    "/book": "book.json",
    "/trades": "trades.json",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--live", action="store_true", help="call Coinbase's real endpoints")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live = config.getoption("--live")
    for item in items:
        if ("live" in item.keywords) != live:
            item.add_marker(pytest.mark.skip(reason="make live" if not live else "not live"))


class Replay:
    """A transport answering from the synthetic exchanges, by the path's end."""

    def __init__(self, routes: Mapping[str, str], statuses: Mapping[str, list[int]] | None = None):
        self.routes = dict(routes)
        self.statuses = {k: list(v) for k, v in (statuses or {}).items()}
        self.asked: list[str] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.asked.append(url)
        path = urlsplit(url).path
        for end, name in self.routes.items():
            if path.endswith(end):
                pending = self.statuses.get(end)
                if pending:
                    status = pending.pop(0)
                    return Response(status, {"retry-after": "1"}, b'{"message":"Slow down"}')
                body = (EXCHANGES / name).read_bytes()
                return Response(200, {"content-type": "application/json"}, body)
        return Response(404, {}, b'{"message":"NotFound"}')


class Sleeps(list[float]):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


def client(
    root: Path, routes: Mapping[str, str] | None = None, **kwargs: Any
) -> tuple[Coinbase, Replay]:
    """A client on the synthetic exchanges, its clock fixed at NOW_NS."""
    replay = Replay({**ROUTES, **(routes or {})}, kwargs.pop("statuses", None))
    return (
        Coinbase(
            RawStore(root),
            transport=replay,
            limiter=kwargs.pop("limiter", RateLimiter(1000.0, 1000)),
            clock_ns=lambda: next(TICKS),
            sleep=kwargs.pop("sleep", Sleeps()),
            **kwargs,
        ),
        replay,
    )


class FakeSocket:
    """Coinbase's feed, replayed from tests/exchanges/stream.jsonl."""

    def __init__(self, lines: list[str]) -> None:
        self.lines, self.sent = list(lines), []  # type: list[str], list[str]

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        if self.lines:
            return self.lines.pop(0)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def replayed_feed(name: str = "stream.jsonl") -> tuple[Any, list[FakeSocket]]:
    sockets: list[FakeSocket] = []

    @asynccontextmanager
    async def connector(url: str) -> AsyncIterator[FakeSocket]:
        socket = FakeSocket((EXCHANGES / name).read_text().splitlines())
        sockets.append(socket)
        yield socket

    return connector, sockets


class Adapter:
    """What the shared conformance suite asks of a plugin: its rows, from its
    own synthetic exchanges, for the suite's venue-neutral scenarios."""

    plugin = "coinbase"
    rows: ModuleType = rows
    #: The suite's pairs, as this venue names them.
    PAIRS = {"BTC/USD": "BTC-USD", "BTC/USDC": "BTC-USDC", "ETH/USD": "ETH-USD"}

    def __init__(self, root: Path) -> None:
        self.root = root
        self.store = RawStore(root)

    def _session(self, routes: Mapping[str, str] | None = None) -> Session:
        coinbase, _ = client(self.root, routes)
        return Session(coinbase)

    def product(self, pair: str) -> Product:
        return self._session().product(self.PAIRS[pair])

    def daily(self, scenario: str) -> tuple[list[Price], list[Bar]]:
        session = self._session({"/candles": f"candles-{scenario}.json"})
        return session.daily(session.product("BTC-USD"), 3, NOW_NS)

    def last(self) -> Price:
        session = self._session()
        return session.last(session.product("BTC-USD"))

    def quote(self) -> Quote:
        session = self._session()
        return session.quote(session.product("BTC-USD"))

    def trades(self, scenario: str = "trades") -> list[Trade]:
        session = self._session({"/trades": f"{scenario}.json"})
        return session.trades(session.product("BTC-USD"))

    def stream(self) -> list[Row]:
        session = self._session()
        connector, _ = replayed_feed()
        product = session.product("BTC-USD")
        return asyncio.run(session.stream([product], 0.2, connector=connector))

    def datasets(self) -> tuple[DatasetDeclaration, ...]:
        return convert.CATALOGUE

    def raw(self, ref: RawRecordRef) -> dict[str, Any] | None:
        return self.store.get(ref.key)


@pytest.fixture
def conformance(tmp_path: Path) -> Adapter:
    return Adapter(tmp_path / "raw")


@pytest.fixture
def exchanges() -> Iterator[Path]:
    yield EXCHANGES


def body(name: str) -> Any:
    return rows.json_decimal((EXCHANGES / name).read_bytes())


def lines(name: str) -> list[Any]:
    return [json.loads(line) for line in (EXCHANGES / name).read_text().splitlines()]
