"""Coinbase's answers, read into the venue's values (the SDK's
`meridian.roles.data.pairs`): the one place
Coinbase's vocabulary is read.

**Assets** (the plan's "Identifiers for a pair"; the product owner's ruling of
2026-10-03 on a venue's balance in a multi-network token):

- **A currency** is a cash instrument, by its ISO 4217 code, where Coinbase's
  `/currencies` says its type is `fiat`.
- **A native coin** carries its CAIP-19 by SLIP-44 coin type (`BTC`, `ETH`),
  from the short table below of chains whose CAIP-2 reference is certain.
- **A token listed on exactly one network**, with a contract address there,
  is that contract and carries its CAIP-19, where the network is a chain
  whose CAIP-2 reference is certain (EVM_CHAINS).
- **Any other token** -- Coinbase's `USDC`, on Ethereum, Solana, Base and
  more; a token on a chain not in the table -- is Coinbase's own instrument,
  its promise that it converts into one of the issuer's contracts: known by
  its code with source `coinbase` alone, never by a contract's CAIP-19, and
  never by Coinbase's `default_network`. Never guessed from a ticker.
- **A stablecoin is a token,** never its currency (decisions/030): USDC is
  Coinbase's USDC instrument though Coinbase converts it to dollars one for
  one.

**Candles** are `[time, low, high, open, close, volume]`, low before high, each
figure a JSON number read from its own text; `time` is the day's start at
00:00 UTC. Coinbase gives neither a volume-weighted price nor a trade count.

**The ticker's** `price` is the last trade, at its `time`, its `trade_id` its
identity; **the level-1 book's** best bid and offer are its first `bids` and
`asks` (`[price, size, orders]`), at its `time`, its `sequence` its identity.

**Trades** (contract v19): `/products/{id}/trades` and the stream's `match`
(and `last_match`, the one it sends on subscribing) state a trade's
`trade_id`, `price`, `size` and `time`, and a `side` that is **the resting
order's**, the maker's (Coinbase's documentation): a `sell` is a buy that
took liquidity, which the SDK's feed records as the aggressor. Coinbase
states no condition codes. **The stream's** `ticker` states the best bid and
offer with their sizes (`best_bid`, `best_bid_size`, `best_ask`,
`best_ask_size`) at its `time`; it is subscribed with `matches` and
`heartbeat`, which says each second that the stream is alive. Every message
is kept as a raw record before it is read, but a heartbeat, which states
nothing.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from meridian.roles.data import (
    NANOS_PER_SECOND,
    SECONDS_PER_DAY,
    Endpoint,
    Limits,
    Session,
    Unread,
    day_start,
    json_decimal,
    number,
)
from meridian.roles.data.pairs import MAKER, Asset, Candle, Listed, Print, Tick, Top

from .stream import Replayed, Socket, websocket
from .venue import BURST, MOST_CANDLES, RATE_PER_SECOND, REST, STREAM, USER_AGENT, Coinbase

VENUE = "coinbase"
#: Coinbase in the venue master: no MIC, so its own code, as a symbol whose
#: source is Coinbase, which the platform's curation adds to its record.
VENUE_IDENTIFIERS: tuple[tuple[str, str, str], ...] = (("symbol", "coinbase", "coinbase"),)
NAME = "Coinbase Exchange"
#: What the venue entitles this plugin to: its public market data, no key.
ENTITLED = "Public market data: every product it lists"

#: Native coins by SLIP-44 coin type, keyed by Coinbase's currency ID.
NATIVE: dict[str, str] = {
    "BTC": "bip122:000000000019d6689c085ae165831e93/slip44:0",
    "ETH": "eip155:1/slip44:60",
}

#: Coinbase's network IDs for EVM chains whose CAIP-2 reference (the chain
#: ID) is certain, for an ERC-20 contract stated on them. Any other network
#: -- Solana, Sui, Cardano, and EVM chains not listed -- gives a token no
#: CAIP-19 until someone checks its namespace's spelling.
EVM_CHAINS: dict[str, str] = {
    "ethereum": "eip155:1",
    "optimism": "eip155:10",
    "polygon": "eip155:137",
    "base": "eip155:8453",
    "arbitrum": "eip155:42161",
}

#: How many pages of Coinbase's trades a gap or a range is read back through:
#: 10,000 trades, minutes of a busy product's.
TRADE_PAGES = 10
#: The stream's channels: trades, the ticker's best bid and offer, and the
#: heartbeat that says it is alive.
CHANNELS = ["matches", "ticker", "heartbeat"]

LIMITS = Limits(
    allowed="Public REST: 10 requests a second per IP, bursts to 15 (Coinbase's documentation)",
    spent=f"At most {RATE_PER_SECOND:g} a second, bursts of {BURST}; a 429 waited out",
    most_candles=MOST_CANDLES,
    history_days=0,
)

_RFC3339 = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})"
)


def rfc3339_ns(text: str) -> int:
    """An RFC 3339 time, to the nanosecond (Coinbase sends nine digits, which
    datetime cannot hold)."""
    match = _RFC3339.fullmatch(text)
    if match is None:
        raise ValueError(f"{text!r} is not an RFC 3339 time")
    year, month, day, hour, minute, second, fraction, zone = match.groups()
    offset = _dt.timedelta()
    if zone != "Z":
        sign = 1 if zone[0] == "+" else -1
        offset = sign * _dt.timedelta(hours=int(zone[1:3]), minutes=int(zone[4:6]))
    moment = _dt.datetime(
        int(year), int(month), int(day), int(hour), int(minute), int(second),
        tzinfo=_dt.timezone(offset),
    )  # fmt: skip
    return int(moment.timestamp()) * NANOS_PER_SECOND + int((fraction or "0").ljust(9, "0"))


def asset(code: str, details: Mapping[str, Any] | None) -> Asset:
    """One Coinbase currency as an asset, from its `/currencies` record (None
    where Coinbase did not list it, so states no network for it)."""
    if details is None:
        return Asset(code, "token")
    name = str(details.get("name") or "")
    if (details.get("details") or {}).get("type") == "fiat":
        return Asset(code, "currency", "iso4217", code, name)
    if code in NATIVE:
        return Asset(code, "token", "caip19", NATIVE[code], name)
    listed = [n for n in details.get("supported_networks") or [] if n.get("id")]
    if len(listed) == 1:
        contract = _contract(listed[0])
        if contract:
            return Asset(code, "token", "caip19", contract, name)
    return Asset(code, "token", name=name)


def _contract(network: Mapping[str, Any]) -> str:
    """The CAIP-19 of the contract on the one network Coinbase lists a token
    on, where that is a chain in EVM_CHAINS and the address an EVM one."""
    chain = EVM_CHAINS.get(str(network.get("id")))
    address = str(network.get("contract_address") or "")
    if chain is None or not (address.startswith("0x") and len(address) == 42):
        return ""
    return f"{chain}/erc20:{address.lower()}"


def listing(products: list[Mapping[str, Any]], currencies: list[Mapping[str, Any]]) -> list[Listed]:
    """Every product Coinbase lists, each side read as an asset. A product not
    `online`, or with trading disabled, is kept with its status: a delisted
    market's history still converts."""
    by_code = {str(item["id"]): item for item in currencies}
    listed: list[Listed] = []
    for item in products:
        base, quote = str(item["base_currency"]), str(item["quote_currency"])
        status = str(item.get("status") or "")
        listed.append(
            Listed(
                product=str(item["id"]),
                base=asset(base, by_code.get(base)),
                quote=asset(quote, by_code.get(quote)),
                tradable=status == "online" and not item.get("trading_disabled", False),
                status=status,
            )
        )
    return sorted(listed, key=lambda p: p.product)


def candles(product: str, body: list[Any], raw_key: str) -> list[Candle]:
    """Daily candles, oldest first, each naming its place in the raw record."""
    read: list[Candle] = []
    for row in sorted(body, key=lambda c: int(c[0])):
        start = int(row[0])
        if start % SECONDS_PER_DAY:
            raise ValueError(f"a daily candle at {start} does not start at 00:00 UTC")
        unread: list[Unread] = []

        def figure(field: str, value: object, unread: list[Unread] = unread) -> Any:
            amount = number(value)
            if amount is None:
                unread.append(Unread(f"candles.{field}", str(value)))
            return amount

        low, high, open_, close, volume = (
            figure(field, row[i])
            for field, i in (("low", 1), ("high", 2), ("open", 3), ("close", 4), ("volume", 5))
        )
        read.append(
            Candle(
                product=product,
                start_s=start,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
                raw_key=f"{raw_key}#{start}",
                unread=tuple(unread),
            )
        )
    return read


def tick(product: str, body: Mapping[str, Any], raw_key: str, received_ns: int) -> Tick:
    """The ticker's last trade."""
    price = number(body.get("price"))
    stated = bool(body.get("time"))
    return Tick(
        product=product,
        price=price,
        at_ns=rfc3339_ns(str(body["time"])) if stated else received_ns,
        stated=stated,
        ident=str(body.get("trade_id") or ""),
        raw_key=raw_key,
        unread=() if price is not None else (Unread("ticker.price", str(body.get("price"))),),
    )


def top(product: str, body: Mapping[str, Any], raw_key: str, received_ns: int) -> Top:
    """The level-1 book's best bid and offer, with their sizes; a side with no
    order is None."""
    bids, asks = body.get("bids") or [], body.get("asks") or []
    unread: list[Unread] = []
    bid, bid_size = _side(bids[0] if bids else None, "book.bids", unread)
    ask, ask_size = _side(asks[0] if asks else None, "book.asks", unread)
    stated = bool(body.get("time"))
    return Top(
        product=product,
        bid=bid,
        ask=ask,
        at_ns=rfc3339_ns(str(body["time"])) if stated else received_ns,
        stated=stated,
        ident=str(body.get("sequence") or ""),
        raw_key=raw_key,
        unread=tuple(unread),
        bid_size=bid_size,
        ask_size=ask_size,
    )


def _side(level: Any, field: str, unread: list[Unread]) -> tuple[Any, Any]:
    """A book level's price and size (`[price, size, ...]`), each None where it
    is not there; a price that does not read is kept as sent."""
    if not level:
        return None, None
    price, size = number(level[0]), number(level[1]) if len(level) > 1 else None
    if price is None:
        unread.append(Unread(f"{field}.price", str(level[0])))
    return price, size


def prints(product: str, body: list[Mapping[str, Any]], raw_key: str) -> list[Print]:
    """`/products/{id}/trades`: each trade, oldest first, its side the maker's."""
    read = [_print(product, item, f"{raw_key}#{item.get('trade_id')}") for item in body]
    return sorted(read, key=lambda p: (p.sequence, p.at_ns))


def _print(product: str, item: Mapping[str, Any], raw_key: str) -> Print:
    """One trade as REST or the stream's `match` states it."""
    price, size = number(item.get("price")), number(item.get("size"))
    unread = [Unread(f"trades.{f}", str(item.get(f))) for f, v in (("price", price),
              ("size", size)) if v is None]  # fmt: skip
    side = str(item.get("side") or "")
    return Print(
        product=product,
        price=price,
        quantity=size,
        at_ns=rfc3339_ns(str(item["time"])),
        ident=str(item.get("trade_id") or ""),
        side=side if side in ("buy", "sell") else "",
        side_of=MAKER if side in ("buy", "sell") else "",
        raw_key=raw_key,
        unread=tuple(unread),
    )


def ticked(body: Mapping[str, Any], raw_key: str, received_ns: int) -> Top:
    """The stream's `ticker`: the best bid and offer with their sizes."""
    unread: list[Unread] = []
    bid, bid_size = _side([body.get("best_bid"), body.get("best_bid_size")]
                          if body.get("best_bid") else None, "ticker.best_bid", unread)  # fmt: skip
    ask, ask_size = _side([body.get("best_ask"), body.get("best_ask_size")]
                          if body.get("best_ask") else None, "ticker.best_ask", unread)  # fmt: skip
    stated = bool(body.get("time"))
    return Top(
        product=str(body.get("product_id") or ""),
        bid=bid,
        ask=ask,
        at_ns=rfc3339_ns(str(body["time"])) if stated else received_ns,
        stated=stated,
        ident=str(body.get("sequence") or ""),
        raw_key=raw_key,
        unread=tuple(unread),
        bid_size=bid_size,
        ask_size=ask_size,
    )


class CoinbaseMarket:
    """Coinbase Exchange's market data, as the shared data plugin's work asks for it."""

    venue = VENUE
    venue_identifiers = VENUE_IDENTIFIERS
    name = NAME

    def __init__(self, client: Coinbase, mode: str = "live") -> None:
        self.client = client
        address = REST if mode == "live" else f"{mode}: no call leaves the deployment"
        stream = STREAM if mode == "live" else f"{mode}: no stream leaves the deployment"
        self.session = Session(
            mode=mode,
            endpoints=(
                Endpoint(
                    "REST", address, "products, currencies, daily candles, ticker, book, trades"
                ),
                Endpoint("WebSocket", stream, "trades, and the best bid and offer"),
            ),  # fmt: skip
            limits=LIMITS,
            health=client.health,
        )
        self._replays = 0

    @property
    def stream_address(self) -> str:
        return STREAM

    async def connect(self, address: str) -> Socket:
        """Coinbase's stream; in synthetic mode its connections replayed in
        turn from files, the last one held open."""
        if self.session.mode == "live":
            return await websocket(address, USER_AGENT)
        sessions: list[list[str]] = getattr(self.client.transport, "stream_sessions", list)()
        held = sessions[min(self._replays, len(sessions) - 1)] if sessions else []
        self._replays += 1
        # Every connection but the last drops once it has said its messages,
        # as the venue's do; the last is held open.
        return Replayed(held, hold=self._replays >= len(sessions))

    def subscriptions(self, names: Sequence[str]) -> list[str]:
        return [json.dumps({"type": "subscribe", "product_ids": list(names),
                            "channels": CHANNELS})]  # fmt: skip

    def heard(self, text: str, received_ns: int) -> list[Print | Top]:
        """One message of the stream, kept first; its trade or its ticker read.
        A heartbeat is neither kept nor read; a subscription's answer or an
        error is kept, and states neither."""
        try:
            body = json_decimal(text)
        except ValueError:
            body = {}
        kind = str(body.get("type") or "unread") if isinstance(body, dict) else "unread"
        if kind == "heartbeat":
            return []
        raw_key = self.client.store.keep_line("stream", kind, {
            "venue": VENUE, "call": "stream", "request": {"method": "GET", "url": STREAM},
            "received_at_ns": received_ns, "status": 101, "headers": {}, "body": text,
        })  # fmt: skip
        if kind == "error":  # a subscription refused: a delisted product, say
            reason = body.get("reason") or body.get("message")
            self.client.health.last_error = f"stream: {reason}"[:200]
        try:
            if kind in ("match", "last_match"):
                return [_print(str(body["product_id"]), body, raw_key)]
            if kind == "ticker":
                return [ticked(body, raw_key, received_ns)]
        except (KeyError, ValueError) as unread:
            self.client.health.last_error = f"stream: a {kind} that did not read: {unread}"[:200]
        return []

    def listing(self) -> list[Listed]:
        products = self.client.products().value
        currencies = self.client.currencies().value
        return listing(products, currencies)

    def candles(self, product: str, first: date, last: date) -> list[Candle]:
        read: list[Candle] = []
        start = day_start(first)
        end = day_start(last)
        while start <= end:
            chunk_end = min(end, start + (MOST_CANDLES - 1) * SECONDS_PER_DAY)
            fetched = self.client.candles(product, start, chunk_end)
            read += [
                c for c in candles(product, fetched.value, fetched.raw_key)
                if start <= c.start_s <= chunk_end
            ]  # fmt: skip
            start = chunk_end + SECONDS_PER_DAY
        return read

    def last(self, product: str) -> Tick:
        fetched = self.client.ticker(product)
        return tick(product, fetched.value, fetched.raw_key, fetched.received_at_ns)

    def top(self, product: str) -> Top:
        fetched = self.client.book(product)
        return top(product, fetched.value, fetched.raw_key, fetched.received_at_ns)

    def trades(self, product: str, since_ns: int = 0) -> list[Print]:
        """The product's trades back to `since_ns`, oldest first, read back a
        page at a time (newest first, by Coinbase's cursor) through at most
        TRADE_PAGES; the latest page where `since_ns` is 0."""
        read: list[Print] = []
        after = ""
        for _ in range(TRADE_PAGES):
            fetched = self.client.trades(product, after)
            page = prints(product, fetched.value, fetched.raw_key)
            if not page or (after and page[-1].sequence >= int(after)):
                break  # nothing older: the start of its history
            read = page + read
            if not since_ns or page[0].at_ns <= since_ns or not page[0].ident:
                break
            after = page[0].ident
        return read
