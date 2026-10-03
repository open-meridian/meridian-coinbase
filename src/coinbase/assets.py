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
- **A token** follows the product owner's ruling (the plan's "a venue's
  balance in a multi-network token is the venue's own instrument"): each
  issuer contract on each chain is its own instrument, and Coinbase's
  balance in a token is one of them only when Coinbase says which.
  - Listed on exactly one network, with a contract address there, it is that
    contract and carries its CAIP-19, where the network is a chain whose
    CAIP-2 reference is certain (the table below). On any other chain, or
    with no contract (another chain's own coin, not in NATIVE), it has none
    yet and resolves by its venue code, which W3.2 reports as missing for a
    person to map.
  - Listed on several networks (Coinbase's `USDC`: Ethereum, Solana, Base,
    ...), or on none, Coinbase has not said which contract it is: it is the
    venue's own instrument, Coinbase's promise that it converts into one of
    those contracts, known by `symbol@coinbase` alone and never by a
    contract's CAIP-19. Coinbase's `default_network` names no contract the
    balance is, so it decides nothing (the ruling: no CAIP-19 by a venue's
    default network).
    The networks Coinbase lists are kept beside it as plain data
    (`Asset.networks`, a placeholder for the "convertible into" relationship
    the entity store's spec will shape).
  Never guessed from a ticker.
- **A stablecoin is a token,** never its fiat currency (decisions/030): USDC
  is Coinbase's USDC instrument even though Coinbase converts it to dollars
  one for one.

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
    where Coinbase did not list it, so states no network for it)."""
    venue_code = symbol(code, VENUE)
    if details is None:
        return Asset(venue_code, "token", venue_instrument=True)
    name = str(details.get("name") or "")
    kind = (details.get("details") or {}).get("type")
    if kind == "fiat":
        return Asset(venue_code, "currency", currency(code), name)
    if code in NATIVE:
        return Asset(venue_code, "token", NATIVE[code], name)
    listed = [n for n in details.get("supported_networks") or [] if n.get("id")]
    if len(listed) == 1:
        return Asset(venue_code, "token", _contract(listed[0]), name)
    networks = tuple(str(n["id"]) for n in listed)
    return Asset(venue_code, "token", None, name, venue_instrument=True, networks=networks)


def _contract(network: dict[str, Any]) -> Identifier | None:
    """The CAIP-19 of the contract on the one network Coinbase lists a token
    on, where that is a chain in EVM_CHAINS and the address is an EVM one."""
    chain = EVM_CHAINS.get(str(network.get("id")))
    address = str(network.get("contract_address") or "")
    if chain is None or not (address.startswith("0x") and len(address) == 42):
        return None
    return caip19(f"{chain}/erc20:{address.lower()}")


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
