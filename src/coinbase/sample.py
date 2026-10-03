"""`python -m coinbase sample --product BTC-USD`: converted rows, for a person
to eyeball.

It asks Coinbase's public endpoints once each (products and currencies for
the product map, the daily candles, the ticker, the level-1 book, recent
trades; with `--stream N`, N seconds of the WebSocket feed), keeps every
response as a raw record under `--raw-dir` (default `recordings/`, which git
ignores: real recordings stay local), and prints each row it converted as
one JSON line, every number its exact decimal text. Nothing is recorded
anywhere else: there is no lake to record into yet.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from . import assets, convert
from .raw import RawStore, storage_root
from .rows import NANOS_PER_DAY, Bar, Price, Product, Quote, Row, Trade, as_dict
from .venue import Coinbase


class Session:
    """Fetch and convert, one call per step: what the CLI, the live smoke
    test and the conformance adapter share."""

    def __init__(self, client: Coinbase) -> None:
        self.client = client
        self._products: dict[str, Product] | None = None

    def products(self) -> dict[str, Product]:
        if self._products is None:
            listed = self.client.products().value
            currencies = self.client.currencies().value
            self._products = assets.products(listed, currencies)
        return self._products

    def product(self, product_id: str) -> Product:
        products = self.products()
        if product_id not in products:
            raise KeyError(f"Coinbase lists no product {product_id!r}")
        return products[product_id]

    def daily(self, product: Product, days: int, now_ns: int) -> tuple[list[Price], list[Bar]]:
        today = now_ns - now_ns % NANOS_PER_DAY
        fetched = self.client.candles(
            product.product.value, convert.DAY, today - (days - 1) * NANOS_PER_DAY, now_ns
        )
        return convert.daily(product, fetched.value, fetched.raw_key, now_ns)

    def last(self, product: Product) -> Price:
        fetched = self.client.ticker(product.product.value)
        return convert.last(product, fetched.value, fetched.raw_key)

    def quote(self, product: Product) -> Quote:
        fetched = self.client.book(product.product.value)
        return convert.quote(product, fetched.value, fetched.raw_key, fetched.received_at_ns)

    def trades(self, product: Product, limit: int = 100) -> list[Trade]:
        fetched = self.client.trades(product.product.value, limit)
        return convert.trades(product, fetched.value, fetched.raw_key)

    async def stream(
        self, products: Sequence[Product], seconds: float, **kwargs: object
    ) -> list[Row]:
        by_id = {p.product.value: p for p in products}
        rows: list[Row] = []
        async for item, ref, _ in self.client.stream(list(by_id), seconds, **kwargs):  # type: ignore[arg-type]
            rows.extend(convert.message(by_id, item, ref))
        return rows


def _print(rows: Sequence[Row]) -> None:
    for row in rows:
        print(json.dumps({"row": type(row).__name__, **as_dict(row)}, sort_keys=False))


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m coinbase sample")
    parser.add_argument("--product", default="BTC-USD", help="a Coinbase product ID")
    parser.add_argument("--days", type=int, default=3, help="daily candles, today included")
    parser.add_argument("--trades", type=int, default=5, help="recent trades")
    parser.add_argument("--stream", type=float, default=0, help="seconds of the WebSocket feed")
    parser.add_argument("--raw-dir", type=Path, default=Path("recordings"))
    args = parser.parse_args(argv)

    store = RawStore(storage_root(args.raw_dir))
    session = Session(Coinbase(store))
    product = session.product(args.product)
    print(f"# {args.product}: {as_dict(product)}", file=sys.stderr)
    closes, bars = session.daily(product, args.days, time.time_ns())
    _print(closes)
    _print(bars)
    _print([session.last(product), session.quote(product)])
    _print(session.trades(product, args.trades))
    if args.stream:
        _print(asyncio.run(session.stream([product], args.stream)))
    print(
        f"# {session.client.calls} calls, {session.client.rate_limited} rate-limited, "
        f"raw records in {store.root}",
        file=sys.stderr,
    )
    return 0
