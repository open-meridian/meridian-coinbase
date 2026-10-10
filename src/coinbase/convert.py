"""Coinbase's answers, read into the venue's values (market.py): the one place
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
`asks`, at its `time`, its `sequence` its identity.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from .market import (
    NANOS_PER_SECOND,
    SECONDS_PER_DAY,
    Asset,
    Candle,
    Endpoint,
    Limits,
    Listed,
    Session,
    Tick,
    Top,
    Unread,
    day_start,
    number,
)
from .venue import BURST, MOST_CANDLES, RATE_PER_SECOND, REST, Coinbase

VENUE = "coinbase"
NAME = "Coinbase Exchange"

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
    """The level-1 book's best bid and offer; a side with no order is None."""
    bids, asks = body.get("bids") or [], body.get("asks") or []
    unread: list[Unread] = []
    bid = number(bids[0][0]) if bids else None
    ask = number(asks[0][0]) if asks else None
    if bids and bid is None:
        unread.append(Unread("book.bids.price", str(bids[0][0])))
    if asks and ask is None:
        unread.append(Unread("book.asks.price", str(asks[0][0])))
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
    )


class CoinbaseMarket:
    """Coinbase Exchange's market data, as the shared dgm asks for it."""

    venue = VENUE
    name = NAME

    def __init__(self, client: Coinbase, mode: str = "live") -> None:
        self.client = client
        address = REST if mode == "live" else f"{mode}: no call leaves the deployment"
        self.session = Session(
            mode=mode,
            endpoints=(
                Endpoint("REST", address, "products, currencies, daily candles, ticker, book"),
            ),
            limits=LIMITS,
            health=client.health,
        )

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
