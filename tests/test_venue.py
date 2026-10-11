"""The client: every answer kept before it is read, the rate limit honoured, a
429 waited out, and synthetic mode's two transports answering as Coinbase
does."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from coinbase.raw import RawStore
from coinbase.synthetic import Recorded, Synthetic
from coinbase.venue import Coinbase, RateLimiter, Response, VenueError


def _client(tmp_path: Path, transport: object) -> Coinbase:
    clock = iter(range(1_791_633_600_000_000_000, 1_791_633_700_000_000_000, 1_000))
    return Coinbase(
        RawStore(tmp_path),
        transport=transport,  # type: ignore[arg-type]
        limiter=RateLimiter(1000.0, 1000, sleep=lambda _: None),
        clock_ns=lambda: next(clock),
        sleep=lambda _: None,
    )


class Scripted:
    def __init__(self, *answers: Response) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        self.asked.append(url)
        assert "User-Agent" in headers
        return self.answers.pop(0)


def test_every_answer_is_kept_before_it_is_read(tmp_path: Path) -> None:
    client = _client(tmp_path, Scripted(Response(200, {"age": "3"}, b'[{"id":"BTC-USD"}]')))
    fetched = client.products()
    kept = client.store.get(fetched.raw_key)
    assert kept is not None and kept["body"] == '[{"id":"BTC-USD"}]'
    assert kept["headers"] == {"age": "3"} and kept["status"] == 200
    assert fetched.raw_key.startswith("responses/2026-10-10/products/")


def test_a_429_is_waited_out_and_counted(tmp_path: Path) -> None:
    scripted = Scripted(Response(429, {"retry-after": "1"}, b'{"message":"slow"}'),
                        Response(200, {}, b"[]"))  # fmt: skip
    client = _client(tmp_path, scripted)
    assert client.currencies().value == []
    assert (client.health.rate_limited, client.health.calls) == (1, 2)


def test_an_error_is_kept_and_said(tmp_path: Path) -> None:
    client = _client(tmp_path, Scripted(Response(404, {}, b'{"message":"NotFound"}')))
    with pytest.raises(VenueError) as refused:
        client.ticker("NOPE-USD")
    assert "NotFound" in str(refused.value) and client.store.get(refused.value.raw_key)
    assert client.health.failures == 1 and "NotFound" in client.health.last_error


def test_no_answer_is_said(tmp_path: Path) -> None:
    def down(url: str, headers: Mapping[str, str]) -> Response:
        raise OSError("connection refused")

    client = _client(tmp_path, down)
    with pytest.raises(VenueError):
        client.products()
    assert client.health.failures == 1


def test_a_live_answer_unchanged_is_not_kept_again(tmp_path: Path) -> None:
    client = _client(tmp_path, Synthetic())
    first, second = client.ticker("BTC-USD"), client.ticker("BTC-USD")
    assert first.raw_key == second.raw_key and first.raw_key.endswith(".jsonl#0")


def test_candles_are_asked_for_a_range_and_answered_as_numbers(tmp_path: Path) -> None:
    transport = Scripted(Response(200, {}, b"[[1791417600,1,2,1,1.50,3]]"))
    client = _client(tmp_path, transport)
    fetched = client.candles("BTC-USD", 1791417600, 1791417600)
    assert (
        "granularity=86400" in transport.asked[0]
        and "start=2026-10-08T00%3A00%3A00Z" in transport.asked[0]
    )
    assert str(fetched.value[0][4]) == "1.50"
    with pytest.raises(ValueError):
        client.candles("BTC-USD", 0, 86_400 * 301)


def test_synthetic_answers_coinbases_shapes(tmp_path: Path) -> None:
    client = _client(tmp_path, Synthetic())
    assert {p["id"] for p in client.products().value} >= {"BTC-USD", "BTC-USDC", "USDC-USD"}
    candles = client.candles("BTC-USD", 1791331200, 1791417600).value
    assert [int(c[0]) for c in candles] == [1791417600, 1791331200], "newest first, as Coinbase"
    with pytest.raises(VenueError):
        client.book("NOPE-USD")


def test_recorded_exchanges_are_replayed_from_a_plugins_raw_records(tmp_path: Path) -> None:
    recording = _client(tmp_path / "kept", Synthetic())
    recording.products()
    recording.currencies()
    recording.candles("BTC-USD", 1791244800, 1791504000)
    recording.ticker("BTC-USD")
    replay = _client(tmp_path / "replayed", Recorded(tmp_path / "kept" / "responses"))
    assert replay.products().value == recording.products().value
    day = replay.candles("BTC-USD", 1791417600, 1791417600).value
    assert [int(c[0]) for c in day] == [1791417600]
    assert str(day[0][4]) == "62000.10"
    assert json.loads(json.dumps(replay.ticker("BTC-USD").value, default=str))["trade_id"] == 8801


def test_trades_are_asked_a_thousand_at_a_time_and_older_by_the_cursor(tmp_path: Path) -> None:
    scripted = Scripted(Response(200, {}, b"[]"), Response(200, {}, b"[]"))
    client = _client(tmp_path, scripted)
    client.trades("BTC-USD")
    client.trades("BTC-USD", after="8804")
    assert scripted.asked[0].endswith("/products/BTC-USD/trades?limit=1000")
    assert scripted.asked[1].endswith("/products/BTC-USD/trades?limit=1000&after=8804")
    older = _client(tmp_path / "s", Synthetic()).trades("BTC-USD", after="8804").value
    assert [t["trade_id"] for t in older] == [8803, 8802, 8801], "older, newest first"


def test_a_recording_replays_its_stream_in_the_order_it_arrived(tmp_path: Path) -> None:
    from coinbase.convert import CoinbaseMarket

    kept = CoinbaseMarket(_client(tmp_path / "kept", Synthetic()), "synthetic")
    kept.client.trades("BTC-USD")
    said = ['{"type":"subscriptions","channels":[]}',
            '{"type":"match","trade_id":9,"side":"buy","size":"0.1","price":"1",'
            '"product_id":"BTC-USD","time":"2026-10-10T11:00:00Z"}']  # fmt: skip
    for at, text in enumerate(said):
        kept.heard(text, 1_791_633_600_000_000_000 + at)
    replay = Recorded(tmp_path / "kept" / "responses")
    assert replay.stream_sessions() == [said]
    trades = _client(tmp_path / "replayed", replay).trades("BTC-USD").value
    assert [t["trade_id"] for t in trades][:2] == [8806, 8805]


def test_a_stream_line_as_the_first_recorder_kept_it_is_replayed(tmp_path: Path) -> None:
    # The recordings of 2026-10-03 keep each stream message as its text and
    # when it arrived, before the stream's raw records named their call.
    match = '{"type":"match","trade_id":9,"side":"buy","size":"0.1","price":"1"}'
    lines = [{"received_at_ns": 2, "text": match}, {"received_at_ns": 1, "text": "first"}]
    (tmp_path / "stream").mkdir()
    (tmp_path / "stream" / "1.jsonl").write_text("\n".join(json.dumps(x) for x in lines))
    assert Recorded(tmp_path).stream_sessions() == [["first", match]]
