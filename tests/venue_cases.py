"""Coinbase's side of the dgm suite: this plugin's synthetic exchanges, named for
what each of the suite's cases asks a source to present.

tests/test_suite.py, the same file in meridian-kraken, runs the SDK's `dgm`
suite unchanged against each plugin's own conversion; this module is the one
place it learns which venue it is holding. Each answer comes through the
plugin's real client, raw records and reading (synthetic.py's transport over
the exchanges this package carries, `src/coinbase/synthetic/`), with
invented values; real recordings are never committed (Coinbase's Market Data
Terms; the plan's Q11).
"""

from __future__ import annotations

import copy
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from coinbase import page, raw, synthetic
from coinbase.convert import CoinbaseMarket
from coinbase.dgm import Dgm, Standing
from coinbase.market import Market
from coinbase.products import ProductMap
from coinbase.raw import RawStore
from coinbase.synthetic import Synthetic
from coinbase.venue import Coinbase, RateLimiter

__all__ = ["Dgm", "ProductMap", "Standing", "market", "page", "raw", "synthetic"]

SYNTHETIC = Path(__file__).parent.parent / "src" / "coinbase" / "synthetic"

#: The venue's name as a symbol's source, and the plugin's.
VENUE = "coinbase"
#: The suite's clock: 2026-10-10 12:00 UTC, the day still forming.
NOW_NS = 1_791_633_600 * 1_000_000_000
TODAY = date(2026, 10, 10)
#: A day whose candles are complete.
CLOSED = date(2026, 10, 8)
#: A base asset priced in both a currency and a stablecoin: Coinbase's BTC
#: (BTC-USD, and BTC-USDC on Coinbase's own USDC instrument).
BASE = "BTC"
STABLE_BASE = "BTC"
#: A base whose close has more decimal places than a float holds (TKN-USD).
EXACT_BASE = "TKN"
#: A base whose daily candle states no volume-weighted price: every
#: Coinbase candle.
BAR_BASE = "BTC"
#: A currency priced in another: Coinbase Exchange lists no product between
#: two currencies, so it presents no FX rate (README, "What it cannot serve").
FX_BASE = ""
#: An asset whose identifiers the suite answers as meeting two records.
AMBIGUOUS = "PLY"
#: The forming day's candle, as read twice while it fills.
FORMING_PRODUCT = "BTC-USD"
FORMING = [
    [1791590400, "61900.00", "62200.00", "61990.55", "62010.25", "120.5"],
    [1791590400, "61850.00", "62300.00", "61990.55", "62155.75", "240.25"],
]


def _instant(_: float) -> None:
    return None


def market(now_ns: int = NOW_NS, forming: int | None = None) -> Market:
    """Coinbase's synthetic exchange through the plugin's own client, its
    answers kept in a fresh store; `forming` adds the forming day's candle,
    as read the first or second time."""
    directory = SYNTHETIC
    if forming is not None:
        held = Path(tempfile.mkdtemp(prefix="coinbase-synthetic-"))
        for name in ("products", "currencies", "ticker", "book"):
            (held / f"{name}.json").write_text((SYNTHETIC / f"{name}.json").read_text())
        candles: dict[str, Any] = json.loads((SYNTHETIC / "candles.json").read_text())
        candles = copy.deepcopy(candles)
        candles[FORMING_PRODUCT].append(FORMING[forming])
        (held / "candles.json").write_text(json.dumps(candles))
        directory = held
    store = RawStore(Path(tempfile.mkdtemp(prefix="coinbase-raw-")))
    client = Coinbase(
        store,
        transport=Synthetic(directory),
        limiter=RateLimiter(1000.0, 1000, sleep=_instant),
        clock_ns=lambda: now_ns,
        sleep=_instant,
    )
    return CoinbaseMarket(client, "synthetic")


#: The last trade's price each of BASE's products states now, as its text.
LIVE_LAST = {"BTC-USD": "62000.11", "BTC-USDC": "62004.90"}
#: The product quoted in a stablecoin, and that stablecoin's code.
STABLE_PRODUCT, STABLE = "BTC-USDC", "USDC"
#: A product the venue lists and no longer trades.
DELISTED = "OLD-USD"
#: The close BASE's first product states for CLOSED, as its text.
CLOSED_CLOSE = ("BTC-USD", "62000.10")
#: The close EXACT_BASE states for CLOSED, as its text.
EXACT_CLOSE = "0.000012345678901234"
