# meridian-coinbase

Coinbase Exchange's public market data in an Open Meridian deployment's lake:
a data plugin. It records each product's daily close and bar, its last
trade price and best bid and offer, and from contract v19 every trade and
the best bid and offer with their sizes, streamed from Coinbase's WebSocket
feed, for the instruments a deployment's readers ask about, every figure
exactly as Coinbase stated it and every code converted at the edge; and it
keeps the order book's depth from that feed as raw records, until the lake
has a kind for it. No key: Coinbase's market data is public.

It is one of the lake's crypto pair, with
[meridian-kraken](https://github.com/open-meridian/plugin-kraken): each runs the SDK's
data suite and its checks for a pairs venue unchanged against its own conversion
(meridian-design `plans/the-lake-prices-the-book.md`, rows 6 and 19); what the two do alike is
the SDK's (`meridian.roles.data.pairs`, open-meridian 0.33.1), never copied
between them.

**Status.** 0.10.0, built on open-meridian 0.33.1 (contract v28: its feed delay reported, a crossed quote recorded invalid at the edge; contract v27: the stream's liveness recorded; the data suite's v27 cases; the book's depth kept raw, open question 232; its work the SDK's role helpers), holding the
role `data`.

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
  data plugin's read from contract v18 as ruled 2026-10-10) and names Coinbase's
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
- **The product map**, kept in the plugin's storage (`meridian.roles.data.pairs.ProductMap`): a
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
  `heartbeat`, and `level2_batch` for depth, all public), kept open while
  any want stands. Every trade is
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
- **Depth, kept raw** (open question 232, ruled 2026-10-17). No lake kind
  holds the book's levels yet, so the products on the stream are subscribed
  to `level2_batch` as well, in a subscription of its own: the whole book
  as a `snapshot`, then every `l2update` (each level's new size, `"0"` a
  level gone, batched every 50 ms). Each message is kept whole as a raw
  record and read into no row: the snapshot and its updates rebuild the
  book at any moment, so they are converted, losing nothing, once the
  market-data intent places a depth kind. The depth of a busy product is
  far more than its trades: an admin sizes the raw responses' window for it.
- **Kept open, with no gap.** A stream that drops, or says nothing for 30
  seconds, is opened again after a wait doubling from one second to a
  minute; each time it opens, the trades since the last one recorded are
  read back from `/products/{id}/trades` (ten pages of 1,000 at most) and
  recorded, so the lake has no hole and a reader catches up from it by the
  watermark it last saw. A trade heard twice -- the history and the stream
  overlap -- is sent once. A want for a range of trades, or for a quote now,
  is answered from REST.
- **A restart's gap, read back** (contract v20). A plugin holds nothing it
  cannot lose, so a restart leaves a gap in the trades it streams. Started
  again, it hears each standing want again and, before a subject goes back
  on the stream, reads from the lake the last trade it recorded of it
  (`ListTrades` with `latest_recorded`) and records the trades Coinbase's
  history states after it (`meridian.roles.data.backfill_restart`), once per
  subject; a trade recorded again is answered unchanged by its row key.
- **The stream's liveness** (contract v27; ruling 418). Coinbase sends only
  on a change, and a `heartbeat` each second for each product streamed:
  every message heard, the heartbeat among them, is the stream's sign of
  life, recorded once a pass as the `live` dataset's liveness
  (`RecordLiveness`, through the SDK's `pairs.Feed` and `Wants.liveness`),
  which confirms every quote in force; never a row. The feed is real time,
  so no dataset declares a delay (`declared_delay_ns` is 0). From 0.10.0 each row streamed
  or kept current has its age at the edge recorded, its feed delay, reported
  every 10 seconds (ruling 518).
- **Its licences** (contract v20): it reads which of its own datasets a
  deployment admin has licensed, on start and each minute, so its Datasets
  page says so exactly.

### What it cannot serve

- **What the suite asks and Coinbase never states.** Of the SDK's data
  suite's 44 cases (contract v27), twenty are not presented, each named with
  why (`tests/venue_cases.py`, and the SDK's `PAIRS_NOT_PRESENTED` for what no
  pairs venue presents), as the suite allows of a case about a kind
  of data (`about`) or a field its source never states (`about_field`,
  contract v20): `an-fx-rate` (Coinbase Exchange lists no product
  between two currencies; Kraken lists fiat pairs and presents it),
  `a-condition-converted` and `a-condition-not-converted` (Coinbase states
  no condition codes: a crypto trade is regular), and `a-trade-withdrawn`
  (Coinbase's feed never withdraws a trade it has stated), and
  `the-takers-side-stated` (Coinbase names the resting order's side, never
  the taker's; `the-makers-side-inverted` holds it to the other side), and
  contract v22's `reads-a-calendar` and `asks-for-a-settlement-date` (a
  venue trading 24/7: it reads no settlement calendar and never computes a
  settlement date), and contract v23's three outcome cases and v26's two
  event-group cases (Coinbase Exchange lists no event contract), and
  contract v27's seven rates cases (a pairs venue publishes no rates), and
  contract v28's option-chain, filings, holdings, dividend and rating cases
  (the SDK's list) and its duplicate and gap cases (Coinbase numbers each
  product's messages on a sequence of its own, and the edge's checks follow
  one per dataset). The other 26 pass, `reports-its-feed-delay` and
  `a-crossed-quote-is-recorded-invalid` among them, three answered by the SDK, and `records-a-datasets-liveness` on the
  stream's heartbeat alone, the case as it is stated (the SDK's producer
  states a ticker).
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
tests and sample data use synthetic exchanges (`src/coinbase/synthetic/`),
shaped exactly as Coinbase documents and sends its answers, with invented
values and invented tokens. A developer's recordings of Coinbase's real
answers stay outside the repository and are replayed locally
(`make e2e-recorded`).

## Settings

| Setting | What it does |
|---|---|
| Sample data (`sample_data`) | A developer's setting, shown only on a development deployment: answer from the synthetic exchanges this plugin carries instead of calling Coinbase, or from a developer's recorded exchanges where its storage holds them (`recorded/`). |
| Raw responses' window (`responses_window_days`, `responses_past_window`) | The SDK's, for the plugin's one kind of raw record: how long Coinbase's answers stay in its storage (30 days by default), and whether a day past it is archived, kept or deleted. |

No secret: Coinbase's public market data needs no key.

## Its pages, under Manage

The data role's two pages (meridian-design
`spec/plugin-pages-follow-their-role.md`), the same sections, rows, labels
and "not set up yet" states as every data plugin's, drawn from the SDK's
role templates (`meridian.roles.data`); Coinbase's nuance only at their
extension points. A data plugin shows no market data: viewing prices is for
the reading roles.

- **Connection**: "Key" -- the mode (Live, or Sample data), "No key needed",
  what Coinbase entitles it to (public data: every product it lists) and, the
  role's row for a source of one venue, the venue master's ID it resolved;
  "Limits and use" -- what Coinbase allows and what the plugin spends of it,
  its calls and the rate-limited ones waited out, the last call and the last
  error; "Stream" -- the session: open or not, the products on it, its
  reconnects and messages and its last error.
- **Datasets**: "Served" -- each dataset of its catalogue, its data, how its
  rows arrive, its day, its default terms and whether a deployment admin has
  licensed it ("Licensed" or "Not licensed yet", read from the deployment
  from contract v20), what it recorded and declined and when it last
  recorded; "Wants" -- the wants it heard and the standing wants it keeps
  current, searched and paged by the kit's `om-pager`; "Subjects" -- whether
  the deployment lets it read an instrument's record; then a section under
  Coinbase's name with the product map (products listed, and mapped for the subjects
  the lake asked for; assets not resolved). Before the lake has asked
  anything it says the next step: "No wants yet", a deployment admin
  licensing its datasets on Data sources.

Its Summary carries the data role's figures, in the role's order:
Connection, Entitled at the vendor, Stream and Last recorded. Both pages
fit one screen at 1440x900 and 390x844, rows one line each.

### Offered to agents

Each page is a read tool on the deployment's MCP surface, answering the record
the page shows: `read_connection` and `read_datasets`, at the plugin's admin
level. The plugin has no route that changes anything.

## Raw responses

Every answer Coinbase sends, an error as much as a candle, is kept in the
storage the deployment grants the plugin before anything is read from it,
with the request that asked for it, its status and freshness headers, and
when it arrived (`meridian.edge.RawStore`); a live answer is a line of its day's file, added
only when it changed, and each message of the stream a line of its day's
file for its type (a heartbeat, which states nothing, is not kept): the
book's depth among them, `stream/snapshot.jsonl` and `stream/l2update.jsonl`,
the only place it is kept until a depth kind is placed. Each row names its raw record (`RawRecordRef`) and
where in it the row came from. Kept in units of a UTC day under
`responses/`, moved past the window through the SDK.

## Proven against a released runtime

    make e2e

runs the plugin with sample data on core's plugin harness, the runtime and
harness of the core it pins by digest, beside the e2e's reader
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
heard, and each product's latest quote with its sizes, the book's depth
kept raw, both read tools
answering what the pages show, and `store lake` numbering each dataset's
rows with no holes (`e2e/run.py` says each step).

    make e2e-recorded RECORDED=<dir> DAY=<a day it holds>

runs the same replaying a developer's recorded exchanges, reading the day
named and holding each row to its shape rather than to the synthetic values:
a directory of this plugin's raw records of Coinbase's real answers, REST
and the stream's messages, recorded under personal use, never committed.

## Working on it

    make ci-local        # every gate: lint, tests, plugin check, the image, e2e, the pair the same
    make test            # the tests, the SDK's data suite among them
    make preview         # preview/: each page on synthetic data, linking the kit
    make install-hooks   # git push runs ci-local first

`AGENTS.md` is for any coding agent working on it; `CLAUDE.md` leads Claude
Code there. The documentation for a deployment admin is in `docs/`.

## Licence

Apache-2.0. See `LICENSE` and `NOTICE`. Coinbase is a trademark of its owner;
this project is not affiliated with or endorsed by Coinbase.
