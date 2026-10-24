# Overview

The Coinbase plugin puts Coinbase Exchange's public market data into your
deployment's lake, where the plugins that value and report on your book read
it. It needs no key: Coinbase's market data is public.

It is a data plugin: its first-use path, its two pages and its Summary figures are every data plugin's, described once on [Using a data plugin](https://open-meridian.dev/how-to/using-a-data-plugin/). These sections cover what is Coinbase's own.

## Its role

It holds one role, `data`: it records prices and bars into the lake, with
Coinbase's codes converted to your deployment's instruments, and keeps
Coinbase's answers in its own storage. It shows no prices itself: reading
them is for the reporting, portfolio, compliance and signal plugins.

## What it records

- **Daily**: each product's close and bar for a UTC day. Coinbase has no
  official close, so the close is the last price of the day ending at 00:00
  UTC; the day still forming is recorded and corrected as it fills.
- **Live**: the last trade's price and the best bid and offer, at most once
  a second for each instrument and kind, while a reader keeps asking; and
  the best bid and offer with their sizes, as a quote, streamed from
  Coinbase's live feed while a reader follows the instrument.
- **Trades**: every trade of each product an instrument is the base of,
  streamed from Coinbase's live feed while a reader follows the instrument, each
  with the side that took liquidity (Coinbase names the resting order's side, so the plugin records the other side as the one that took liquidity). A crypto trade has no
  condition codes, so every trade counts for a day's open, high, low, close
  and volume. Trades are a dataset of their own, so you license and keep
  them apart from live prices.

## If the feed drops

If the live feed drops, the plugin connects again and reads the trades it
missed from Coinbase's trade history, so nothing is lost and a reader catches up
from the lake.

It records what readers ask for, not the whole exchange: when a reader asks
for a price nothing has recorded, the lake asks the plugin, which records it
or says why it cannot.

## How current it is

Coinbase's live feed is real time, so the plugin declares no delay. The feed
sends a price only when it changes, and a heartbeat each second. The plugin
records each sign of life from the feed for the live dataset, so the lake
knows a best bid and offer that has not changed is still current. A
heartbeat is never recorded as a price.

## How it names what it prices

A Coinbase product such as BTC-USD names a market, not an asset. The plugin
records BTC's price in dollars: BTC is the instrument, and the dollar what the
price is in. It finds each in your deployment's instruments by a global
identifier where Coinbase states one (the dollar's ISO 4217 code, bitcoin's
CAIP-19), and otherwise by Coinbase's own code.

A price in a stablecoin is recorded in that stablecoin, never in the
currency it tracks: a BTC-USDC price is in Coinbase's USDC, not in dollars.
Coinbase's USDC is its own instrument, a promise to convert into one of
Circle's contracts, so it carries no contract's identifier.

## What it never makes up

- A figure is recorded exactly as Coinbase stated it, never rounded and never
  through a float.
- A value Coinbase did not send is left out, never zero: Coinbase's candles
  carry no volume-weighted price, so its bars carry none.
- A rate between two currencies: Coinbase lists none, so the plugin records
  none.

## What it keeps

Coinbase's answers, as received, in the storage your deployment gives the
plugin, for 30 days by default, each price naming the answer it came from.
Past that window, a day's answers are archived, kept or deleted as you set
it.

Your deployment's lake has no place for an order book's levels yet, so the
plugin records no depth there. Among its answers is the order book's depth
from the live feed, for each product it streams: the whole book when the
feed opens, then every change. A busy product's depth takes far more storage
than its trades, so set the window with it in mind.
