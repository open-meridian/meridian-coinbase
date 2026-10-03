"""Coinbase's market data, converted into the lake's rows (rows.py).

The edge is the only place Coinbase's vocabulary is read. Each converter takes
what Coinbase sent, parsed with Decimals, the product it was for (assets.py),
and the raw record it was kept as, and returns rows naming the base asset as
their subject and pricing it in the quote asset.

- **The daily close** (the plan's Q5): Coinbase has no official close, so a
  dataset declares its day, the UTC day, and a daily candle (granularity
  86,400, its time the bucket's start at 00:00 UTC) gives kind `close` for
  business date D, valid from D 00:00Z until D+1 00:00Z, its `published`
  source time the candle's end. The day still forming (its end after now)
  has no `published` time and keeps its row key, so each later reading is a
  restatement under the same key, never a new row.
- **Bars** from the same candles: Coinbase gives neither a VWAP nor a trade
  count, so both are unset, never zero. Its candles are
  `[time, low, high, open, close, volume]`: low before high.
- **Trades:** Coinbase's `side` is the **maker's** order side, so the
  aggressor is the other side. A side it has never sent is not known, the
  side as reported beside it.
- **Last and quote:** the ticker's `price` is the last trade, at its `time`;
  the level-1 book's best bid and offer, with their sizes, are the quote.
- A value that does not convert -- not a number, or past the contract's
  Decimal -- is None with the venue's text in an `AsReported`, its scheme
  naming Coinbase's field (`coinbase:candles.close`).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator, Mapping
from decimal import Decimal
from typing import Any

from .rows import (
    NANOS_PER_DAY,
    NANOS_PER_SECOND,
    REGULAR,
    AsReported,
    Bar,
    DatasetDeclaration,
    DeclaredDay,
    Money,
    ObservationMeta,
    Price,
    Product,
    Quote,
    RawRecordRef,
    Row,
    Source,
    SourceTime,
    Trade,
    as_reported,
    exact,
    rfc3339_ns,
    utc_date,
)

VENUE = "coinbase"
DAY = 86_400

#: The catalogue (the spec's "The catalogue"; the plan's Q21): a daily dataset
#: of closes and bars, kept, its day the UTC day; and a live one of last
#: prices, quotes and trades. The keys are proposals.
DAILY = DatasetDeclaration(
    key="daily",
    vendor="Coinbase",
    data_types=("price", "bar"),
    modes=("pull",),
    cadence="P1D",
    day=DeclaredDay(calendar="UTC", ends_at="00:00"),
)
LIVE = DatasetDeclaration(
    key="live",
    vendor="Coinbase",
    data_types=("price", "quote", "trade"),
    modes=("pull", "stream"),
    cadence="PT1S",
)
CATALOGUE = (DAILY, LIVE)


class _Values:
    """Converts one record's values, collecting what did not convert."""

    def __init__(self, product: Product, endpoint: str) -> None:
        self.product, self.endpoint = product, endpoint
        self.unconverted: list[AsReported] = []

    def number(self, field: str, value: object) -> Decimal | None:
        converted = exact(value, f"{VENUE}:{self.endpoint}.{field}")
        if isinstance(converted, AsReported):
            self.unconverted.append(converted)
            return None
        return converted

    def money(self, field: str, value: object) -> Money | None:
        amount = self.number(field, value)
        return None if amount is None else self.product.money(amount)

    def positive(self, field: str, value: object) -> Decimal | None:
        """A quantity, which the contract has more than zero."""
        amount = self.number(field, value)
        if amount is not None and amount <= 0:
            self.unconverted.append(as_reported(f"{VENUE}:{self.endpoint}.{field}", value))
            return None
        return amount


def _pid(product: Product) -> str:
    return product.product.value


def daily(
    product: Product, candles: list[Any], raw_key: str, now_ns: int
) -> tuple[list[Price], list[Bar]]:
    """Closes and bars from daily candles, oldest first."""
    closes: list[Price] = []
    bars: list[Bar] = []
    for candle in sorted(candles, key=lambda c: int(c[0])):
        start = int(candle[0])
        if start % DAY:
            raise ValueError(f"a daily candle at {start} does not start at 00:00 UTC")
        start_ns = start * NANOS_PER_SECOND
        end_ns = start_ns + NANOS_PER_DAY
        date = utc_date(start_ns)
        published = () if end_ns > now_ns else (SourceTime("published", end_ns),)
        raw = RawRecordRef(f"{raw_key}#{start}")
        values = _Values(product, "candles")
        low, high, open_, close = (
            values.money(field, candle[i])
            for field, i in (("low", 1), ("high", 2), ("open", 3), ("close", 4))
        )
        volume = values.number("volume", candle[5])
        if volume is not None and volume < 0:
            values.unconverted.append(as_reported(f"{VENUE}:candles.volume", candle[5]))
            volume = None

        daily_meta = ObservationMeta(
            row_key=f"close/{_pid(product)}/{date}",
            subjects=(product.subject(),),
            source=Source(DAILY.key),
            valid_from_ns=start_ns,
            valid_until_ns=end_ns,
            business_date=date,
            source_times=published,
            raw=raw,
            unconverted=tuple(u for u in values.unconverted if u.scheme.endswith(".close")),
        )
        closes.append(Price(daily_meta, "close", close))
        bar_meta = dataclasses.replace(
            daily_meta,
            row_key=f"bar/{_pid(product)}/P1D/{date}",
            unconverted=tuple(values.unconverted),
        )
        bars.append(Bar(bar_meta, open=open_, high=high, low=low, close=close, volume=volume))
    return closes, bars


def last(product: Product, ticker: Mapping[str, Any], raw_key: str) -> Price:
    """The ticker's last trade price, at the trade's time."""
    values = _Values(product, "ticker")
    at = rfc3339_ns(str(ticker["time"]))
    price = values.money("price", ticker.get("price"))
    return Price(
        ObservationMeta(
            row_key=f"last/{_pid(product)}/{ticker.get('trade_id') or at}",
            subjects=(product.subject(),),
            source=Source(LIVE.key),
            valid_from_ns=at,
            source_times=(SourceTime("event", at),),
            raw=RawRecordRef(raw_key),
            unconverted=tuple(values.unconverted),
        ),
        "last",
        price,
    )


def quote(product: Product, book: Mapping[str, Any], raw_key: str, received_at_ns: int) -> Quote:
    """The level-1 book's best bid and offer; a side with no order is unset."""
    values = _Values(product, "book")
    bids, asks = book.get("bids") or [], book.get("asks") or []
    at = rfc3339_ns(str(book["time"])) if book.get("time") else received_at_ns
    return Quote(
        ObservationMeta(
            row_key=f"quote/{_pid(product)}/{book.get('sequence') or at}",
            subjects=(product.subject(),),
            source=Source(LIVE.key),
            valid_from_ns=at,
            source_times=(SourceTime("event", at),) if book.get("time") else (),
            raw=RawRecordRef(raw_key),
            unconverted=tuple(values.unconverted),
        ),
        bid=values.money("bids.price", bids[0][0]) if bids else None,
        ask=values.money("asks.price", asks[0][0]) if asks else None,
        bid_quantity=values.positive("bids.size", bids[0][1]) if bids else None,
        ask_quantity=values.positive("asks.size", asks[0][1]) if asks else None,
    )


#: Coinbase's side is the maker's; the aggressor took the other side.
_AGGRESSOR = {"sell": "buy", "buy": "sell"}


def trade(
    product: Product, item: Mapping[str, Any], raw_key: str, endpoint: str = "trades"
) -> Trade:
    """One trade, its aggressor the side opposite Coinbase's maker side."""
    values = _Values(product, endpoint)
    side = str(item.get("side", ""))
    aggressor = _AGGRESSOR.get(side, "")
    if not aggressor:
        values.unconverted.append(as_reported(f"{VENUE}:{endpoint}.side", side))
    at = rfc3339_ns(str(item["time"]))
    trade_id = int(item["trade_id"])
    price = values.money("price", item.get("price"))
    quantity = values.positive("size", item.get("size"))
    return Trade(
        ObservationMeta(
            row_key=f"trade/{_pid(product)}/{trade_id}",
            subjects=(product.subject(),),
            source=Source(LIVE.key),
            valid_from_ns=at,
            source_times=(SourceTime("event", at),),
            raw=RawRecordRef(raw_key),
            unconverted=tuple(values.unconverted),
        ),
        price=price,
        quantity=quantity,
        attributes=REGULAR,
        aggressor=aggressor,  # type: ignore[arg-type]
        source_sequence=trade_id,
    )


def trades(product: Product, items: list[Any], raw_key: str) -> list[Trade]:
    """Trades oldest first (Coinbase sends the newest first)."""
    ordered = sorted(items, key=lambda item: int(item["trade_id"]))
    return [trade(product, item, f"{raw_key}#{item['trade_id']}") for item in ordered]


def message(
    products: Mapping[str, Product], item: Mapping[str, Any], ref_key: str
) -> Iterator[Row]:
    """The rows one feed message carries: a `ticker` gives the last price and
    the quote at its time, a `match` (or the `last_match` sent on
    subscribing) a trade. Anything else -- subscriptions, heartbeats -- none,
    and an `error` is raised."""
    kind = item.get("type")
    if kind == "error":
        raise ValueError(f"Coinbase's feed refused: {item.get('message')} {item.get('reason', '')}")
    product = products.get(str(item.get("product_id", "")))
    if product is None:
        return
    if kind == "ticker":
        values = _Values(product, "feed.ticker")
        at = rfc3339_ns(str(item["time"]))
        meta = {
            "subjects": (product.subject(),),
            "source": Source(LIVE.key),
            "valid_from_ns": at,
            "source_times": (SourceTime("event", at),),
            "raw": RawRecordRef(ref_key),
        }
        price = values.money("price", item.get("price"))
        yield Price(
            ObservationMeta(
                row_key=f"last/{_pid(product)}/{item.get('trade_id') or at}",
                unconverted=tuple(values.unconverted),
                **meta,  # type: ignore[arg-type]
            ),
            "last",
            price,
        )
        quoted = _Values(product, "feed.ticker")
        bid = quoted.money("best_bid", item.get("best_bid")) if item.get("best_bid") else None
        ask = quoted.money("best_ask", item.get("best_ask")) if item.get("best_ask") else None
        bid_size = item.get("best_bid_size")
        ask_size = item.get("best_ask_size")
        yield Quote(
            ObservationMeta(
                row_key=f"quote/{_pid(product)}/{item.get('sequence') or at}",
                unconverted=tuple(quoted.unconverted),
                **meta,  # type: ignore[arg-type]
            ),
            bid=bid,
            ask=ask,
            bid_quantity=quoted.positive("best_bid_size", bid_size) if bid_size else None,
            ask_quantity=quoted.positive("best_ask_size", ask_size) if ask_size else None,
        )
    elif kind in ("match", "last_match"):
        yield trade(product, item, ref_key, endpoint="feed.match")
