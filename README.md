# meridian-coinbase

Coinbase Exchange's public market data in an Open Meridian deployment's lake:
a `dgm` plugin. It records each product's daily close and bar, its last
trade price and best bid and offer, and from contract v19 every trade and
the best bid and offer with their sizes, streamed from Coinbase's WebSocket
feed, for the instruments a deployment's readers ask about, every figure
exactly as Coinbase stated it and every code converted at the edge. No key:
Coinbase's market data is public.

It is the first half of the lake's crypto pair, with
[meridian-kraken](https://github.com/open-meridian/meridian-kraken): the two
pass one `dgm` suite unchanged between them (meridian-design
`plans/the-lake-prices-the-book.md`, rows 6 and 19).

**Status.** 0.2.0, built on open-meridian 0.23.0 (contract v19). Not
released, uploaded or launched anywhere.

## What it does

Three datasets, declared from code in its catalogue (`declaration.py`):

| Dataset | Data | Modes | Day | Coinbase's standard terms |
|---|---|---|---|---|
| `<instance>:daily` | a close and a bar per product per day | pull, push | `Etc/UTC`, ending at 00:00 | kept, shown inside the organisation |
| `<instance>:live` | the last trade's price and the best bid and offer, as prices; the best bid and offer with their sizes, as a quote | pull, stream | `Etc/UTC`, ending at 00:00 | kept two days, shown inside the organisation |
| `<instance>:trades` | every trade | pull, stream | `Etc/UTC`, ending at 00:00 | kept two days, shown inside the organisation |

- **What the lake wants, recorded.** A reader reads a price nothing has
  recorded; the lake asks this plugin (a want), which records it against the
  want or declines each subject with why: `not_covered` (no product's base is
  it), `beyond_history`, `source_silent` (Coinbase has nothing for it). A
  standing want keeps its subjects current until the lake withdraws it: the
  live dataset at most once a second per subject and kind, the daily
  dataset's forming day every five minutes.
- **The daily close** is the last price of the UTC day: Coinbase has no
  official close, so the catalogue declares the day (`day_time_zone`
  `Etc/UTC`, `day_end_minute` 0) and a daily candle gives kind `close` for
  its business date, a plain date. The day still forming is recorded valid
  until its end, with no published time, and restated under the same row key
  as it fills; a completed day carries its published time, the candle's
  end. Bars carry what Coinbase gave and nothing it did not: no
  volume-weighted price and no trade count.
- **Every subject is the deployment's own record.** The lake asks for
  instruments by the deployment's ID, most of them a custodian's records
  that Coinbase never resolved. The plugin reads each record (W3.6, a
  `dgm`'s read from contract v18 as ruled 2026-10-10) and names Coinbase's
  asset it is by its identifiers: Coinbase's code (`symbol` at `coinbase`),
  else the global identifier Coinbase states for an asset, else another
  source's symbol that is Coinbase's code (never for a record that is a
  security, by its class or a CUSIP or ISIN: ETH is a share's ticker too).
  Where the record lacks
  Coinbase's identifiers they are reported beside the one it matched, so
  the record carries them; where that meets another record it is reported,
  and the subject is served all the same. A record naming none of
  Coinbase's assets is declined, not covered. Nothing is resolved for an
  asset no subject is: no record is minted for each asset Coinbase lists.
- **The product map**, kept in the plugin's storage (`products.py`): a
  product names a market, not an asset, so its base asset is a row's subject
  and its quote asset what the price is in. Which asset each subject is is
  kept there, and each quote asset of a subject's products is resolved
  through the deployment's instrument store by the one global identifier
  Coinbase's own statements give it, with its code as a `symbol` whose
  source is `coinbase`, a record minted only where none resolves:
  - a currency (Coinbase's `fiat`) by its ISO 4217 code;
  - a native coin (BTC, ETH) by its SLIP-44 CAIP-19;
  - a token Coinbase lists on exactly one network, with its contract there,
    by that contract's CAIP-19;
  - any other token -- Coinbase's USDC, listed on several networks -- by its
    code alone: Coinbase's own instrument, its promise that it converts into
    one of the issuer's contracts (the product owner's ruling of
    2026-10-03), never a contract's CAIP-19 and never Coinbase's default
    network's.
  A quote asset that does not resolve (its identifiers meet two records) is
  reported, once, and every product quoted in it left out.
- **Money names an instrument.** A price in a currency names it by its ISO
  4217 code, which core resolves to the currency's cash instrument. A price
  in a token -- a BTC-USDT or BTC-USDC price -- names the token's own
  instrument, exactly as stated, and never a fiat code: a USDC price is never
  a dollar price. A reader values it through a dataset's price of the
  stablecoin (USDC-USD, recorded like any product), never by assuming 1.
- **The venue** is resolved in the platform's venue master by its code
  (`symbol` `coinbase`, source `coinbase`: ISO 10383 has no MIC for Coinbase
  Exchange's spot market), and each row names its `VEN-` ID. A deployment
  that does not hold it gets each row with the venue left empty and the code
  beside it as reported, and the miss reported, re-resolved at the next
  mapping.
- **Exact.** Every figure is a `Decimal` from Coinbase's own text: its candles
  are JSON numbers, read from their text, never through a float. A value
  with more places than the contract's Decimal holds is not rounded.
- **Trades and quotes, streamed** (contract v19). A standing want of the
  live or the trades dataset -- a reader following an instrument's latest
  quote, say -- puts the products of its subjects on Coinbase's WebSocket
  feed (`wss://ws-feed.exchange.coinbase.com`: `matches`, `ticker` and
  `heartbeat`, public), kept open while any want stands. Every trade is
  recorded in `trades`, never conflated, and each product's best bid and
  offer, with their sizes, in `live` at most once a second; only for
  subjects under a standing want, in batches of at most 500. A crypto trade
  has no condition codes: it is regular, eligible to set every statistic of
  a bar in its venue's view and the consolidated one. Coinbase names **the
  resting order's side**, so the plugin records the other as the aggressor,
  the side that took liquidity. Keyed by its product and Coinbase's trade ID
  (`BTC-USD:t:812345678`), valid from its time, with no business date; a
  quote by its product and instant, a side with no order left unset, never
  zero.
- **Kept open, with no gap.** A stream that drops, or says nothing for 30
  seconds, is opened again after a wait doubling from one second to a
  minute; each time it opens, the trades since the last one recorded are
  read back from `/products/{id}/trades` (ten pages of 1,000 at most) and
  recorded, so the lake has no hole and a reader catches up from it by the
  watermark it last saw. A trade heard twice -- the history and the stream
  overlap -- is sent once. A want for a range of trades, or for a quote now,
  is answered from REST.

### What it cannot serve

- **What the suite asks and Coinbase never states.** Of the SDK's `dgm`
  suite's 21 cases (contract v19), four are not presented, each named with
  why in `tests/venue_cases.py`, as the suite allows of a case about a kind
  of data (`about`): `an-fx-rate` (Coinbase Exchange lists no product
  between two currencies; Kraken lists fiat pairs and presents it),
  `a-condition-converted` and `a-condition-not-converted` (Coinbase states
  no condition codes: a crypto trade is regular), and `a-trade-withdrawn`
  (Coinbase's feed never withdraws a trade it has stated). The other 17
  pass unchanged.
- **The venue in its catalogue.** The catalogue is declared from code, and
  the venue master's ID for Coinbase Exchange is minted by the platform, so
  `DatasetDeclaration.venue_id` is empty; each row names the venue by the ID
  it resolves at run time.
- **A required figure that does not read** (a close past the contract's
  Decimal): the row is left unrecorded and counted on the Datasets page, its
  raw record kept. The SDK's `Price` carries no price left not known.

## Coinbase's terms

A summary, not legal advice; read the terms themselves before relying on
them. Coinbase Exchange's Market Data Terms allow an organisation to use and
show Coinbase's market data within itself, and forbid redistributing or
displaying it outside the organisation, or building applications for other
end users with it, without Coinbase's written consent. The catalogue's
standard terms say so (kept, shown, not one person's), and a deployment
admin confirms or replaces them in the deployment's licence on the Data
sources page. Nothing here says that a deployment meets Coinbase's terms.

So **no real Coinbase response is committed** to this public repository: the
tests and synthetic mode use synthetic exchanges (`src/coinbase/synthetic/`),
shaped exactly as Coinbase documents and sends its answers, with invented
values and invented tokens. A developer's recordings of Coinbase's real
answers stay outside the repository and are replayed locally
(`make e2e-recorded`).

## Settings

| Setting | What it does |
|---|---|
| Synthetic mode (`synthetic`) | A developer's setting, shown only on a development deployment: answer from the synthetic exchanges this plugin carries instead of calling Coinbase, or from a developer's recorded exchanges where its storage holds them (`recorded/`). |
| Raw responses' window (`responses_window_days`, `responses_past_window`) | The SDK's, for the plugin's one kind of raw record: how long Coinbase's answers stay in its storage (30 days by default), and whether a day past it is archived, kept or deleted. |

No secret: Coinbase's public market data needs no key.

## Its pages, under Manage

A `dgm` shows no market data: viewing prices is for the reading roles.

- **Connection**: where it answers from (Coinbase, or synthetic mode), the
  endpoints (REST and the stream), what Coinbase allows (public REST 10
  requests a second per IP, bursts to 15) and what the plugin spends of it
  (at most 5 a second, a 429 waited out), its calls, rate limits met and
  failures, the last error, the venue master's ID it resolved, and the
  stream's session: open or not, how many products are on it, how often it
  opened and dropped, its messages and the last one's time.
- **Datasets**: each dataset of its catalogue, the product map (products
  listed, and mapped for the subjects the lake asked for; assets not
  resolved), what Coinbase entitles it to (public data, no key: every
  product it lists), and the wants it heard, standing ones first, each with
  what it recorded and declined.

Both fit one screen at 1440x900 and 390x844, rows one line each, the wants
paged by the kit's `om-pager` with its search above them (kit 0.11.0),
which narrows them as typed.

### Offered to agents

Each page is a read tool on the deployment's MCP surface, answering the record
the page shows: `read_connection` and `read_datasets`, at the plugin's admin
level. The plugin has no route that changes anything.

## Raw responses

Every answer Coinbase sends, an error as much as a candle, is kept in the
storage the deployment grants the plugin before anything is read from it,
with the request that asked for it, its status and freshness headers, and
when it arrived (`raw.py`); a live answer is a line of its day's file, added
only when it changed, and each message of the stream a line of its day's
file for its type (a heartbeat, which states nothing, is not kept). Each row names its raw record (`RawRecordRef`) and
where in it the row came from. Kept in units of a UTC day under
`responses/`, moved past the window through the SDK.

## Proven against a released runtime

    make e2e

runs the plugin in synthetic mode on core's plugin harness, the runtime and
harness of core's v19 main pinned by digest, beside the e2e's reader
(`e2e/reader.py`, a `reporting` plugin run from the plugin's image, holding
`custody` to resolve a custodian's records and `signal` to read trades and
quotes): the catalogue listed, the listing read with no record minted for
any asset, the three datasets licensed and the reader entitled, a custodian's bitcoin (by its symbol alone) read and
named, and a day's closes wanted and recorded against the want (BTC-USD's in
dollars, BTC-USDC's on USDC's own instrument, exactly), the dollar declined,
BTC's live prices kept current until withdrawn, BTC's products streamed --
the synthetic venue dropping the first connection, the plugin opening it
again and reading back the trades it missed -- every trade recorded once
with its aggressor, read over the day and after the reader's watermark and
heard, and each product's latest quote with its sizes, both read tools
answering what the pages show, and `store lake` numbering each dataset's
rows with no holes (`e2e/run.py` says each step).

    make e2e-recorded RECORDED=<dir> DAY=<a day it holds>

runs the same replaying a developer's recorded exchanges, reading the day
named and holding each row to its shape rather than to the synthetic values:
a directory of this plugin's raw records of Coinbase's real answers, REST
and the stream's messages, recorded under personal use, never committed.

## Working on it

    make ci-local        # every gate: lint, tests, plugin check, the image, e2e, the pair the same
    make test            # the tests, the SDK's dgm suite among them
    make preview         # preview/: each page on synthetic data, linking the kit
    make install-hooks   # git push runs ci-local first

`AGENTS.md` is for any coding agent working on it; `CLAUDE.md` leads Claude
Code there. The documentation for a deployment admin is in `docs/`.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`. Coinbase is a trademark of its owner;
this project is not affiliated with or endorsed by Coinbase.
