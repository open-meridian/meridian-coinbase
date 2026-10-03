"""Coinbase's products, mapped to the assets they trade (the plan's
"Identifiers for a pair").

A product ID (`BTC-USD`) names a market, not an asset, so it is never a row's
subject: the base asset is, priced in the quote asset. Each side resolves
through W3.1 by its global identifier, which this module derives from what
Coinbase states and nothing else:

- **A currency** is a cash instrument, by its ISO 4217 code, when Coinbase's
  `/currencies` says its type is `fiat`.
- **A native coin** carries its CAIP-19 by SLIP-44 coin type (`BTC`, `ETH`),
  from the short table below of chains whose CAIP-2 reference is certain.
- **A token** carries a CAIP-19 by contract address only where Coinbase
  states the network and the address: its `default_network`, when that is a
  chain with a known CAIP-2 reference, and that network's `contract_address`.
  Otherwise none, and the token resolves by its venue code, which W3.2
  reports as missing for a person to map. Never guessed from a ticker.
- **A stablecoin is a token,** never its fiat currency (decisions/030): USDC
  is the USDC token even though Coinbase converts it to dollars one for one.

The product's own ID stays a source-scoped `symbol` (source `coinbase`), the
idea the coordinator called `coinbase-product`, and the venue's asset codes
likewise; neither is ever a key.
"""

from __future__ import annotations

from typing import Any

from .rows import Asset, Identifier, Product, caip19, currency, symbol

VENUE = "coinbase"

#: Native coins by SLIP-44 coin type, keyed by Coinbase's currency ID.
NATIVE: dict[str, Identifier] = {
    "BTC": caip19("bip122:000000000019d6689c085ae165831e93/slip44:0"),
    "ETH": caip19("eip155:1/slip44:60"),
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


def asset(code: str, details: dict[str, Any] | None) -> Asset:
    """One Coinbase currency as an asset, from its `/currencies` record (None
    where Coinbase did not list it)."""
    venue_code = symbol(code, VENUE)
    if details is None:
        return Asset(venue_code, "token")
    name = str(details.get("name") or "")
    kind = (details.get("details") or {}).get("type")
    if kind == "fiat":
        return Asset(venue_code, "currency", currency(code), name)
    if code in NATIVE:
        return Asset(venue_code, "token", NATIVE[code], name)
    return Asset(venue_code, "token", _contract(details), name)


def _contract(details: dict[str, Any]) -> Identifier | None:
    network = details.get("default_network")
    chain = EVM_CHAINS.get(str(network))
    if chain is None:
        return None
    for listed in details.get("supported_networks") or []:
        if listed.get("id") == network:
            address = str(listed.get("contract_address") or "")
            if address.startswith("0x") and len(address) == 42:
                return caip19(f"{chain}/erc20:{address.lower()}")
    return None


def products(listed: list[dict[str, Any]], currencies: list[dict[str, Any]]) -> dict[str, Product]:
    """Every product Coinbase lists, by its ID, each side resolved as above.
    A product that is not `online`, or whose trading is disabled, is kept
    with its status, never dropped: a delisted market's history still
    converts."""
    by_code = {str(item["id"]): item for item in currencies}
    mapped: dict[str, Product] = {}
    for item in listed:
        pid = str(item["id"])
        base, quote = str(item["base_currency"]), str(item["quote_currency"])
        status = str(item.get("status") or "")
        tradable = status == "online" and not item.get("trading_disabled", False)
        mapped[pid] = Product(
            product=symbol(pid, VENUE),
            base=asset(base, by_code.get(base)),
            quote=asset(quote, by_code.get(quote)),
            status=status,
            tradable=tradable,
        )
    return mapped
