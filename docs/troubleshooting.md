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
deployment's instruments. Their products are left out until a person resolves
the conflict on the Instruments page.

## A subject declined

A reader asked for an instrument the plugin cannot price: no Coinbase product
has it as its base (`not covered`), or Coinbase has no candle for that day
(`source silent`).

## A price in USDC, not dollars

As it should be: a price quoted in a stablecoin is recorded in that
stablecoin. A reader values it through a price of the stablecoin, such as
Coinbase's USDC-USD.

## No FX rates

Coinbase Exchange lists no product between two currencies. Use another source
for FX.

## Still stuck

Open the plugin's Connection page and copy its last error into a ticket with
**Report a problem**.
