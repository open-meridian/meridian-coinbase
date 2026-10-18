"""Coinbase's side of the data role's checks: this plugin's synthetic exchanges,
named for what each of the checks asks a source to present.

tests/test_data_role.py runs the SDK's checks for a pairs venue
(`meridian.roles.data.testing.PairsChecks`) -- the data suite unchanged,
the venue's work past the suite's cases, and the pages -- against this
plugin's own conversion; this module is the one place they learn which
venue they are holding. Each answer comes through the plugin's real client,
raw records and reading (synthetic.py's transport over the exchanges this
package carries, `src/coinbase/synthetic/`), with invented values; real
recordings are never committed (Coinbase's Market Data Terms; the plan's
Q11).
"""

from __future__ import annotations

import copy
import json
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from meridian.edge import RawStore
from meridian.roles.data.pairs import MAKER, Feed, Market

from coinbase import page
from coinbase.convert import CoinbaseMarket
from coinbase.stream import Replayed, Socket, Stream
from coinbase.synthetic import Synthetic
from coinbase.venue import Coinbase, RateLimiter

__all__ = ["page"]

PACKAGE = Path(__file__).parent.parent / "src" / "coinbase"
#: The plugin's own modules no float may reach.
CONVERSION = (PACKAGE / "convert.py", PACKAGE / "synthetic.py")
#: The plugin's stream: its own session over its own transport.
STREAM = Stream

SYNTHETIC = PACKAGE / "synthetic"

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
        for kept in SYNTHETIC.iterdir():
            (held / kept.name).write_text(kept.read_text())
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

# ── Trades and quotes (contract v19) ─────────────────────────────────────────

#: Whose side Coinbase names on a trade: the resting order's.
SIDE_OF = MAKER
#: BASE's products on the stream, by their names on it.
STREAM_NAMES = ["BTC-USD", "BTC-USDC"]
#: Every trade the synthetic stream and history state for BASE's products,
#: by product, in order: the first connection drops after 8802, so on
#: reopening 8803 to 8806 are read back from `/trades`, and the second
#: connection's 8806 is heard again and not sent again.
STREAMED = {"BTC-USD": ["8801", "8802", "8803", "8804", "8805", "8806", "8807"],
            "BTC-USDC": ["4403"]}  # fmt: skip
GAP = {"8803", "8804", "8805", "8806"}
#: The side that took liquidity, by trade: the maker's side inverted.
AGGRESSORS = {"8801": "AGGRESSOR_SELL", "8802": "AGGRESSOR_BUY", "8803": "AGGRESSOR_BUY",
              "8804": "AGGRESSOR_SELL", "8805": "AGGRESSOR_BUY", "8806": "AGGRESSOR_SELL",
              "8807": "AGGRESSOR_SELL", "4403": "AGGRESSOR_SELL"}  # fmt: skip
#: 8802 as the stream states it, exactly.
TRADE_PRICE, TRADE_QUANTITY = ("BTC-USD", "8802"), ("62010.01", "0.0125")
#: The last best bid and offer each product's stream states: bid, its size,
#: ask, its size.
LAST_QUOTES = {"BTC-USD": ("62011.79", "0.92000000", "62011.80", "0.33000000"),
               "BTC-USDC": ("62005.10", "0.10000000", "62005.40", "0.25000000")}  # fmt: skip
#: A base whose level-1 book has bids and no offer: TKN-USD's.
ONE_SIDED_BASE = "TKN"
#: A trade on BASE's dollar product naming the resting order's side, a sell:
#: a buy took liquidity.
MAKER_SELL = (
    '{"type":"match","trade_id":8902,"maker_order_id":"5b1a0c3e-0000-4000-8000-000000008902",'
    '"taker_order_id":"9c2b1d4f-0000-4000-8000-000000008902","side":"sell","size":"0.0125",'
    '"price":"62510.01","product_id":"BTC-USD","sequence":200102,'
    '"time":"2026-10-10T11:59:58.123456Z"}'
)
#: The stream's ticker for BASE's dollar product: both sides, with sizes.
TICKER = (
    '{"type":"ticker","sequence":200103,"product_id":"BTC-USD","price":"62510.01",'
    '"open_24h":"61500.00","volume_24h":"904.71","low_24h":"61400.00","high_24h":"62600.00",'
    '"volume_30d":"27141.30","best_bid":"62510.00","best_bid_size":"0.84000000",'
    '"best_ask":"62510.02","best_ask_size":"0.50000000","side":"buy",'
    '"time":"2026-10-10T11:59:58.500000Z","trade_id":8902,"last_size":"0.0125"}'
)
#: Each case of the suite about trades or quotes, the stream's message that
#: presents it.
STREAM_CASES = {"a-trade-recorded": MAKER_SELL, "the-makers-side-inverted": MAKER_SELL,
                "a-standing-want-streamed": MAKER_SELL, "a-quote-recorded": TICKER}  # fmt: skip
#: Why each case Coinbase never presents is not (meridian.suites: a case about
#: a kind of data, `about`, the plugin never publishes).
NOT_PRESENTED = {
    "an-fx-rate": "Coinbase Exchange lists no product between two currencies: no FX rate",
    "a-condition-converted": "Coinbase states no condition codes: a crypto trade is regular",
    "a-condition-not-converted": "Coinbase states no condition codes: none to leave unconverted",
    "a-trade-withdrawn": "Coinbase's feed never withdraws a trade it has stated",
    "the-takers-side-stated": "Coinbase names the resting order's side on a trade, never the "
    "taker's: the side that took liquidity is the other one (the-makers-side-inverted)",
    "reads-a-calendar": "a crypto venue trading 24/7: it reads no settlement calendar",
    "asks-for-a-settlement-date": (
        "records prices, bars and trades as Coinbase Exchange publishes them; never computes a "
        "settlement date"
    ),
    "records-an-outcome": "Coinbase Exchange lists no event contract: no outcome to record",
    "restates-a-disputed-outcome": "Coinbase Exchange lists no event contract: no outcome disputed",
    "records-a-partial-payout": "Coinbase Exchange lists no event contract: no payout to settle",
}
#: A restart's gap (contract v20): the last trade the lake holds of BASE's
#: dollar product, by its product, trade ID and time; and the trades the
#: venue's history states after it, in order.
RESTARTED = ("BTC-USD", "8804", 1_791_633_593_500_000_000)
BACKFILLED = ["8805", "8806"]


def replayed(messages: list[str]) -> Socket:
    """A connection saying `messages` and dropping, as a venue's does."""
    return Replayed(messages, hold=False)


def stream_sessions(feed: Feed) -> list[list[str]]:
    """The messages of each of the synthetic venue's connections, in turn."""
    sessions: list[list[str]] = feed.market.client.transport.stream_sessions()  # type: ignore[attr-defined]
    return sessions


def raw_store(feed: Feed) -> RawStore:
    """The raw records the plugin's client keeps."""
    store: RawStore = feed.market.client.store  # type: ignore[attr-defined]
    return store
