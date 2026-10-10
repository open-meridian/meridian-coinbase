"""What this version declares beside its role (W8.1, W4.1; contract v18).

**Its catalogue** (spec/the-lake, "The catalogue"; the plan's Q5 and Q21),
declared from code and read the same way at registration and by `meridian
plugin upload`:

- `daily`: each product's close and bar for a UTC day, its day ending at
  00:00 UTC (`day_time_zone` `Etc/UTC`, `day_end_minute` 0, as the plan
  rules for a venue with no official close), pulled for what the lake
  wants and pushed for a standing want; kept.
- `live`: the last trade's price and the best bid and offer, at most once a
  second per subject and kind, pulled for the latest or kept current for a
  standing want; kept two days.

Each licence is what Coinbase's standard terms say, which the deployment's
licence confirms or replaces, never whether a deployment meets them: the
Market Data Terms let an organisation keep and show Coinbase's market data
within itself, and forbid redistributing or displaying it outside, or
building applications for other end users, without Coinbase's written
consent (README, "Coinbase's terms"; not legal advice).

`venue_id` is empty: the venue master's ID for Coinbase Exchange is minted by
the platform, not known to the code a catalogue is declared from, so each row
names the venue by the ID it resolves at run time (dgm.py), and the
catalogue names none (README, "The venue").

**Its storage**: one kind of raw record, Coinbase's responses as received,
kept a month by default (raw.py); the SDK declares the kind's two window
settings. **Its settings**: synthetic mode, a developer's (synthetic.py). No
secret: Coinbase's public market data needs no key.
"""

import meridian
from meridian import DatasetDeclaration, DatasetLicence, Declaration, RecordKind, Storage

from .raw import KIND, LABEL, WINDOW_DAYS

VENDOR = "Coinbase"
SYNTHETIC = "synthetic"

SETTINGS = [
    meridian.Setting(
        SYNTHETIC,
        bool,
        label="Synthetic mode",
        default=False,
        developer=True,
        description=(
            "Answer from built-in synthetic Coinbase responses instead of calling Coinbase, "
            "to develop and test without reaching it."
        ),
    ),
]

CATALOGUE = [
    DatasetDeclaration(
        key="daily",
        vendor=VENDOR,
        data_types=["meridian.v1.Price", "meridian.v1.Bar"],
        modes=["pull", "push"],
        cadence=86_400,
        history=0,
        licence_default=DatasetLicence(kept=True, derived_use=True, display=True),
        day_time_zone="Etc/UTC",
        day_end_minute=0,
    ),
    DatasetDeclaration(
        key="live",
        vendor=VENDOR,
        data_types=["meridian.v1.Price"],
        modes=["pull", "stream"],
        cadence=1,
        history=0,
        licence_default=DatasetLicence(kept=True, retention_days=2, display=True),
        day_time_zone="Etc/UTC",
        day_end_minute=0,
    ),
]

DECLARATION = Declaration(
    settings=SETTINGS,
    storage=Storage(kinds=[RecordKind(KIND, LABEL, window_days=WINDOW_DAYS)]),
    catalogue=CATALOGUE,
)
