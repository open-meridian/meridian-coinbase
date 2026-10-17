"""Synthetic mode: Coinbase's answers from files, never from Coinbase.

A developer's setting (`synthetic`, shown only on a development deployment)
turns it on. The client asks exactly as it asks Coinbase, keeps each answer as
a raw record and reads it the same way; only the transport differs:

- `Synthetic`: the synthetic exchanges this package carries (`synthetic/`),
  shaped exactly as Coinbase Exchange documents and sends its answers --
  candles as JSON numbers, every other figure a string -- with invented
  values, and invented tokens (TKN on one network with a contract, PLY on
  several). They are what CI and `make e2e` replay.
- `Recorded`: a developer's own recorded exchanges -- the raw records a
  plugin kept of Coinbase's real answers, recorded under personal use --
  replayed by `make e2e-recorded` from a directory that is never committed
  (Coinbase's Market Data Terms; the plan's Q11).

Each also answers the stream (contract v19) with `stream_sessions`: the
messages of each connection in turn, which the market replays
(convert.py's `connect`, stream.py's `Replayed`). The synthetic stream is
`synthetic/stream.jsonl`, a message a line exactly as Coinbase sends it; a
line `{"synthetic": ...}`, never sent, is where the synthetic venue drops the
connection, so the next one opens and the gap is read from `trades.json`. A
recording replays the messages it kept, in the order they arrived, as one
connection.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Mapping
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any

from .venue import Response

_HEADERS = {"cache-control": "no-store"}


def _found(body: Any) -> Response:
    return Response(200, dict(_HEADERS), json.dumps(body).encode("utf-8"))


def _missing() -> Response:
    return Response(404, dict(_HEADERS), b'{"message":"NotFound"}')


def _route(url: str) -> tuple[list[str], dict[str, str]]:
    split = urllib.parse.urlsplit(url)
    parts = [urllib.parse.unquote(p) for p in split.path.split("/") if p]
    return parts, dict(urllib.parse.parse_qsl(split.query))


def _epoch(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())


class Synthetic:
    """Answers from a directory of synthetic exchanges: `products.json` and
    `currencies.json` as Coinbase's bodies, `candles.json`, `ticker.json`,
    `book.json` and `trades.json` each a body per product (trades newest
    first), and `stream.jsonl` the stream's messages."""

    def __init__(self, directory: Path | None = None) -> None:
        root = directory or Path(str(resources.files("coinbase") / "synthetic"))
        self.held = {
            name: json.loads((root / f"{name}.json").read_text(encoding="utf-8"))
            for name in ("products", "currencies", "candles", "ticker", "book", "trades")
        }
        lines = (root / "stream.jsonl").read_text(encoding="utf-8").splitlines()
        self.sessions: list[list[str]] = [[]]
        for line in lines:
            if line.startswith('{"synthetic"'):
                self.sessions.append([])
            elif line.strip():
                self.sessions[-1].append(line)

    def stream_sessions(self) -> list[list[str]]:
        return self.sessions

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        parts, query = _route(url)
        if parts == ["products"]:
            return _found(self.held["products"])
        if parts == ["currencies"]:
            return _found(self.held["currencies"])
        if len(parts) == 3 and parts[0] == "products":
            product, call = parts[1], parts[2]
            if call == "candles":
                rows = self.held["candles"].get(product)
                if rows is None:
                    return _missing()
                start, end = _epoch(query["start"]), _epoch(query["end"])
                within = [r for r in rows if start <= int(r[0]) <= end]
                return Response(200, dict(_HEADERS), _candles(within))
            if call == "trades" and product in self.held["trades"]:
                after = int(query.get("after") or 0)
                older = [t for t in self.held["trades"][product]
                         if not after or int(t["trade_id"]) < after]  # fmt: skip
                return _found(older[: int(query.get("limit", "100"))])
            if call in ("ticker", "book") and product in self.held[call]:
                return _found(self.held[call][product])
        return _missing()


def _candles(rows: list[list[Any]]) -> bytes:
    """Candles newest first, as Coinbase sends them, each figure the text it
    was written with (a JSON number, never through a float)."""
    ordered = sorted(rows, key=lambda r: -int(r[0]))
    return ("[" + ",".join("[" + ",".join(str(v) for v in r) + "]" for r in ordered) + "]").encode()


class Recorded:
    """Answers from a developer's recorded raw records (`meridian.edge.RawStore`'s files under a
    `responses/` directory): the latest answer kept for each request's path,
    and for candles every candle kept for the product, within the range
    asked."""

    def __init__(self, directory: Path) -> None:
        self.latest: dict[str, str] = {}
        self.candles: dict[str, dict[int, str]] = {}
        heard: list[tuple[int, str]] = []
        for path in sorted(directory.rglob("*")):
            if path.suffix == ".json":
                records = [json.loads(path.read_text(encoding="utf-8"))]
            elif path.suffix == ".jsonl":
                records = [
                    json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                ]
            else:
                continue
            for record in records:
                if record.get("call") == "stream":
                    heard.append((int(record["received_at_ns"]), str(record["body"])))
                    continue
                if "call" not in record and "text" in record and "received_at_ns" in record:
                    # A stream message as the recorder of 2026-10-03 kept it,
                    # before the stream's raw records: its text and arrival.
                    heard.append((int(record["received_at_ns"]), str(record["text"])))
                    continue
                if record.get("status") != 200:
                    continue
                parts, _ = _route(str(record["request"]["url"]))
                body = str(record["body"])
                if len(parts) == 3 and parts[2] == "candles":
                    for row in _raw_rows(body):
                        self.candles.setdefault(parts[1], {})[int(row.split(",")[0])] = row
                else:
                    self.latest["/".join(parts)] = body
        self.heard = [body for _, body in sorted(heard, key=lambda h: h[0])]

    def stream_sessions(self) -> list[list[str]]:
        return [self.heard]

    def __call__(self, url: str, headers: Mapping[str, str]) -> Response:
        parts, query = _route(url)
        if len(parts) == 3 and parts[2] == "candles":
            held = self.candles.get(parts[1])
            if held is None:
                return _missing()
            start, end = _epoch(query["start"]), _epoch(query["end"])
            rows = [held[t] for t in sorted(held, reverse=True) if start <= t <= end]
            return Response(
                200, dict(_HEADERS), ("[" + ",".join(f"[{r}]" for r in rows) + "]").encode()
            )
        body = self.latest.get("/".join(parts))
        return Response(200, dict(_HEADERS), body.encode()) if body is not None else _missing()


def _raw_rows(body: str) -> list[str]:
    """A candles body's rows as their own text, `t,low,high,open,close,volume`."""
    inner = body.strip()[1:-1].strip()
    if not inner:
        return []
    return [row.strip().strip("[]") for row in inner.split("],")]
