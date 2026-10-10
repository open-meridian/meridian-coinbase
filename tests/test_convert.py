"""Coinbase's answers read into the venue's values: its assets, candles, ticker
and level-1 book (convert.py), on the shapes Coinbase sends."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from coinbase import convert
from coinbase.market import json_decimal, number
from coinbase.synthetic import Synthetic

CURRENCIES = {item["id"]: item for item in Synthetic().held["currencies"]}


def test_a_currency_is_its_iso_4217_cash_instrument() -> None:
    usd = convert.asset("USD", CURRENCIES["USD"])
    assert (usd.kind, usd.scheme, usd.value, usd.currency_code) == (
        "currency",
        "iso4217",
        "USD",
        "USD",
    )


def test_a_native_coin_carries_its_slip44_caip19_whatever_networks_it_lists() -> None:
    btc = convert.asset("BTC", CURRENCIES["BTC"])
    assert (btc.scheme, btc.value) == ("caip19", "bip122:000000000019d6689c085ae165831e93/slip44:0")
    assert convert.asset("ETH", CURRENCIES["ETH"]).value == "eip155:1/slip44:60"


def test_a_token_on_one_network_with_its_contract_carries_that_contracts_caip19() -> None:
    tkn = convert.asset("TKN", CURRENCIES["TKN"])
    assert (tkn.scheme, tkn.value) == (
        "caip19",
        "eip155:1/erc20:0x00000000000000000000000000000000000a0bc1",
    )


def test_a_token_on_several_networks_is_coinbases_own_instrument() -> None:
    for code in ("USDC", "PLY"):
        token = convert.asset(code, CURRENCIES[code])
        assert (token.kind, token.scheme, token.currency_code) == ("token", "", ""), code


def test_a_token_coinbase_does_not_describe_is_its_own_instrument() -> None:
    assert convert.asset("ZZZ", None) == convert.asset("ZZZ", None)
    assert convert.asset("ZZZ", None).scheme == ""


def test_a_token_on_a_chain_with_no_certain_caip2_has_none() -> None:
    held = dict(CURRENCIES["TKN"])
    held["supported_networks"] = [{"id": "solana", "contract_address": "So1ana"}]
    assert convert.asset("TKN", held).scheme == ""


def test_a_stablecoin_is_never_its_currency() -> None:
    listed = {p.product: p for p in convert.listing(Synthetic().held["products"],
                                                     Synthetic().held["currencies"])}  # fmt: skip
    btc_usdc = listed["BTC-USDC"]
    assert btc_usdc.quote.kind == "token" and not btc_usdc.quote.currency_code
    assert not listed["OLD-USD"].tradable and listed["OLD-USD"].status == "delisted"


def test_candles_are_read_from_their_own_text_never_a_float() -> None:
    body = json_decimal("[[1791417600,61750.00,62580.90,62431.27,0.000012345678901234,904.71]]")
    [candle] = convert.candles("BTC-USD", body, "responses/x.json")
    assert candle.close == Decimal("0.000012345678901234")
    assert candle.low == Decimal("61750.00") and str(candle.low) == "61750.00"
    assert (candle.vwap, candle.trade_count) == (None, None)
    assert candle.day == date(2026, 10, 8) and candle.raw_key == "responses/x.json#1791417600"


def test_a_figure_past_the_contracts_decimal_is_kept_as_sent() -> None:
    body = json_decimal("[[1791417600,1,2,1,1.0000000000000000001,5]]")
    [candle] = convert.candles("BTC-USD", body, "k")
    assert candle.close is None
    assert [(u.field, u.text) for u in candle.unread] == [
        ("candles.close", "1.0000000000000000001")
    ]


def test_a_candle_not_on_a_utc_midnight_is_refused() -> None:
    try:
        convert.candles("BTC-USD", [[1791417601, 1, 1, 1, 1, 1]], "k")
    except ValueError as refused:
        assert "00:00 UTC" in str(refused)
    else:
        raise AssertionError("a candle off midnight was read")


def test_the_ticker_and_the_book_at_coinbases_times() -> None:
    ticker = json_decimal(json.dumps(Synthetic().held["ticker"]["BTC-USD"]))
    tick = convert.tick("BTC-USD", ticker, "k", 5)
    assert (tick.price, tick.ident, tick.stated) == (Decimal("62000.11"), "8801", True)
    assert tick.at_ns == convert.rfc3339_ns("2026-10-09T23:59:58.123400000Z")
    book = json_decimal(json.dumps(Synthetic().held["book"]["BTC-USD"]))
    top = convert.top("BTC-USD", book, "k", 5)
    assert (top.bid, top.ask, top.stated) == (Decimal("62000.10"), Decimal("62000.12"), True)
    empty = convert.top("BTC-USD", {"bids": [], "asks": [], "sequence": 1}, "k", 7)
    assert (empty.bid, empty.ask, empty.at_ns, empty.stated) == (None, None, 7, False)


def test_rfc3339_keeps_nine_digits() -> None:
    assert convert.rfc3339_ns("2026-10-09T00:00:00.000000001Z") % 1_000_000_000 == 1
    assert convert.rfc3339_ns("2026-10-09T02:00:00+02:00") == convert.rfc3339_ns(
        "2026-10-09T00:00:00Z"
    )


def test_number_refuses_what_is_not_the_contracts_decimal() -> None:
    assert number("62431.27") == Decimal("62431.27")
    assert number(Decimal("1E+2")) == Decimal("1E+2")
    for refused in (None, True, 1.5, "NaN", "inf", "abc", "0." + "1" * 19):
        assert number(refused) is None, refused
