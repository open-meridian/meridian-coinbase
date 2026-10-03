"""Coinbase's own differences, which the shared suite does not state: its rate
limit, its raw records, its JSON-number candles, its currencies' networks,
its feed, and the CLI. Each against the synthetic exchanges."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from coinbase import assets, convert, sample
from coinbase.raw import RawStore
from coinbase.rows import NANOS_PER_DAY, Price, Quote, Trade
from coinbase.sample import Session
from coinbase.venue import RateLimiter, VenueError

from conftest import EXCHANGES, NOW_NS, FakeSocket, Sleeps, body, client, replayed_feed


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_the_rate_limiter_spends_at_most_its_rate() -> None:
    clock = Clock()
    limiter = RateLimiter(5.0, 5, clock=clock, sleep=clock.sleep)
    for _ in range(15):
        limiter.acquire()
    # Five at once, then one every fifth of a second: ten more take two seconds.
    assert clock.now == pytest.approx(2.0)
    assert limiter.waited == pytest.approx(2.0)


def test_a_429_is_waited_out_and_asked_again(tmp_path: Path) -> None:
    sleeps = Sleeps()
    coinbase, replay = client(tmp_path, statuses={"/ticker": [429, 429]}, sleep=sleeps)
    fetched = coinbase.ticker("BTC-USD")
    assert fetched.value["price"] == "62800.01"
    assert sleeps == [1.0, 1.0] and coinbase.rate_limited == 2 and len(replay.asked) == 3
    # Each answer is kept, the refusals as much as the price.
    statuses = [coinbase.store.get(k)["status"] for k in coinbase.store.records()]  # type: ignore[index]
    assert sorted(statuses) == [200, 429, 429]


def test_a_429_that_persists_is_an_error_naming_its_raw_record(tmp_path: Path) -> None:
    coinbase, _ = client(tmp_path, statuses={"/ticker": [429] * 4})
    with pytest.raises(VenueError) as refused:
        coinbase.ticker("BTC-USD")
    assert refused.value.status == 429 and "Slow down" in str(refused.value)
    assert coinbase.store.get(refused.value.raw_key) is not None


def test_every_response_is_kept_exactly_as_it_arrived(tmp_path: Path) -> None:
    coinbase, _ = client(tmp_path)
    fetched = coinbase.candles("BTC-USD", 86_400, NOW_NS - 2 * NANOS_PER_DAY, NOW_NS)
    record = coinbase.store.get(fetched.raw_key)
    assert record is not None
    assert record["body"] == (EXCHANGES / "candles-daily.json").read_text()
    assert record["call"] == "candles" and record["status"] == 200
    assert "granularity=86400" in record["request"]["url"]
    assert record["received_at_ns"] == fetched.received_at_ns


def test_candles_are_json_numbers_read_as_decimals_from_their_text(tmp_path: Path) -> None:
    coinbase, _ = client(tmp_path, {"/candles": "candles-precise.json"})
    [candle] = coinbase.candles("BTC-USD", 86_400, NOW_NS - NANOS_PER_DAY, NOW_NS).value
    assert candle[4] == Decimal("62000.123456789012345") and isinstance(candle[4], Decimal)
    # What json.loads would have made of it, which the plugin never does.
    assert json.loads("62000.123456789012345") != candle[4]


def test_more_than_300_candles_is_refused_before_asking(tmp_path: Path) -> None:
    coinbase, replay = client(tmp_path)
    with pytest.raises(ValueError, match="300"):
        coinbase.candles("BTC-USD", 86_400, NOW_NS - 301 * NANOS_PER_DAY, NOW_NS)
    assert replay.asked == []


def test_a_token_carries_caip19_only_where_coinbase_states_network_and_address() -> None:
    mapped = assets.products(body("products.json"), body("currencies.json"))
    tkn = mapped["TKN-USD"].base
    # The address as CAIP-19 spells an EVM address: lower case.
    assert tkn.identifier is not None
    assert tkn.identifier.value == "eip155:1/erc20:0x00000000000000000000000000000000000000aa"
    # A chain this plugin does not spell CAIP-19 for gives none; it resolves by its code.
    ply = mapped["PLY-USD"].base
    assert ply.identifier is None
    assert (ply.resolve_by().scheme, ply.resolve_by().source) == ("symbol", "coinbase")
    # USDC is a token on its default network, never the dollar it converts to.
    usdc = mapped["BTC-USDC"].quote
    assert usdc.kind == "token" and usdc.identifier is not None
    assert usdc.identifier.value.startswith("eip155:1/erc20:")


def test_a_delisted_product_is_kept_with_its_status() -> None:
    mapped = assets.products(body("products.json"), body("currencies.json"))
    assert (mapped["BTC-USDC"].status, mapped["BTC-USDC"].tradable) == ("delisted", False)
    assert mapped["BTC-USD"].tradable


def test_coinbases_side_is_the_makers() -> None:
    product = assets.products(body("products.json"), body("currencies.json"))["BTC-USD"]
    item = {
        "trade_id": 1,
        "side": "sell",
        "size": "1",
        "price": "1",
        "time": "2026-10-03T00:00:00Z",
    }
    assert convert.trade(product, item, "k").aggressor == "buy"
    assert convert.trade(product, {**item, "side": "buy"}, "k").aggressor == "sell"


async def test_the_feed_is_subscribed_and_each_message_kept(tmp_path: Path) -> None:
    coinbase, _ = client(tmp_path)
    connector, sockets = replayed_feed()
    session = Session(coinbase)
    rows = await session.stream([session.product("BTC-USD")], 0.2, connector=connector)
    [socket] = sockets
    assert json.loads(socket.sent[0]) == {
        "type": "subscribe",
        "product_ids": ["BTC-USD"],
        "channels": ["ticker", "matches"],
    }
    assert [type(r) for r in rows] == [Price, Quote, Trade]
    # The subscriptions message is message 0; the ticker 1, the match 2.
    assert [r.meta.raw.key.rsplit("#", 1)[1] for r in rows] == ["1", "1", "2"]
    assert coinbase.store.get(rows[2].meta.raw.key)["text"].startswith('{"type":"match"')  # type: ignore[index]


async def test_a_dropped_feed_is_opened_again_after_a_pause(tmp_path: Path) -> None:
    coinbase, _ = client(tmp_path)
    opened: list[int] = []
    pauses: list[float] = []

    @asynccontextmanager
    async def flaky(url: str) -> AsyncIterator[FakeSocket]:
        opened.append(1)
        if len(opened) == 1:
            raise ConnectionResetError("dropped")
        yield FakeSocket((EXCHANGES / "stream.jsonl").read_text().splitlines())

    async def pause(seconds: float) -> None:
        pauses.append(seconds)

    got = [m async for m, _, _ in coinbase.stream(["BTC-USD"], 0.2, connector=flaky, pause=pause)]
    assert len(opened) == 2 and pauses == [1.0] and coinbase.reconnected == 1
    assert [m["type"] for m in got] == ["subscriptions", "ticker", "match"]


def test_an_error_from_the_feed_is_raised() -> None:
    with pytest.raises(ValueError, match="Failed to subscribe"):
        list(convert.message({}, {"type": "error", "message": "Failed to subscribe"}, "k"))


def test_the_cli_prints_each_row_as_exact_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sample, "Coinbase", lambda store: client(store.root)[0])
    monkeypatch.setattr("time.time_ns", lambda: NOW_NS)
    assert sample.main(["--product", "BTC-USD", "--raw-dir", str(tmp_path)]) == 0
    printed = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    kinds = [(p["row"], p.get("kind")) for p in printed]
    assert kinds[:3] == [("Price", "close")] * 3 and ("Quote", None) in kinds
    close = printed[0]
    assert close["price"] == {
        "amount": "62000.12345678",
        "currency": {"scheme": "iso4217", "value": "USD", "source": ""},
    }
    assert close["meta"]["business_date"] == "2026-10-01"
    assert any(RawStore(tmp_path).records())
