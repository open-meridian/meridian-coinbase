# Troubleshooting

## Coinbase is not answering

The Connection page's status says so, with the last error. Coinbase's public
endpoints sit behind a cache and sometimes refuse; the plugin waits out a rate
limit and tries again. Check the deployment can reach api.exchange.coinbase.com.

## Venue master: not held

Your deployment has not pulled Coinbase Exchange from the platform's venue
master. Each price is recorded with its venue left empty and Coinbase named
as reported, and the plugin asks again at its next mapping, once a day.

## An asset not resolved

The Datasets page lists assets whose identifiers matched two of your
deployment's instruments. A product quoted in one is left out until a person
resolves the conflict on the Instruments page; an instrument asked about
whose record met another is still priced.

## A subject declined

A reader asked for an instrument the plugin cannot price: its record names
none of Coinbase's assets -- no Coinbase code, no global identifier Coinbase
states, no other source's symbol that is Coinbase's code -- or no Coinbase
product has it as its base (`not covered`), or Coinbase has no candle for
that day (`source silent`). Add an identifier to the record on the
Instruments page, and the plugin reads it again within a day.

## A price in USDC, not dollars

As it should be: a price quoted in a stablecoin is recorded in that
stablecoin. A reader values it through a price of the stablecoin, such as
Coinbase's USDC-USD.

## No FX rates

Coinbase Exchange lists no product between two currencies. Use another source
for FX.

## The live feed keeps dropping

The Connection page's **Stream** row says how often the feed opened and
dropped, and why it last dropped. The plugin connects again on its own,
waiting longer each time up to a minute, and reads the trades it missed from
Coinbase's history. Check the deployment can reach ws-feed.exchange.coinbase.com on port 443.

## No trades or quotes recorded

They are recorded only while a reader follows the instrument (a standing
want of the live or trades dataset), and only once the dataset is licensed
and the reader entitled to it on the **Data sources** page.

## Still stuck

Open the plugin's Connection page and copy its last error into a ticket with
**Report a problem**.
