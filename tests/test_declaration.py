"""The declaration: the catalogue declared from code, as registration and
`meridian plugin upload` read it."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from coinbase.declaration import CATALOGUE, DECLARATION, SYNTHETIC


def test_two_datasets_daily_and_live_on_the_utc_day() -> None:
    assert [d.key for d in CATALOGUE] == ["daily", "live"]
    for dataset in CATALOGUE:
        assert (dataset.vendor, dataset.day_time_zone, dataset.day_end_minute) == (
            "Coinbase",
            "Etc/UTC",
            0,
        )
        assert dataset.venue_id == "", "the venue's ID is resolved at run time, never invented"
    daily, live = CATALOGUE
    assert list(daily.data_types) == ["meridian.v1.Price", "meridian.v1.Bar"]
    assert list(live.data_types) == ["meridian.v1.Price"]
    assert daily.licence_default and daily.licence_default.kept
    assert live.licence_default and live.licence_default.retention_days == 2
    assert not any(d.licence_default and d.licence_default.personal_use for d in CATALOGUE)


def test_no_secret_and_synthetic_a_developers_setting() -> None:
    [setting] = DECLARATION.settings
    assert (setting.name, setting.developer, setting.secret) == (SYNTHETIC, True, False)
    assert DECLARATION.storage is not None


def test_upload_reads_the_same_declaration() -> None:
    printed = subprocess.run(
        [str(Path(sys.executable).parent / "meridian-declaration"),
         "coinbase.declaration:DECLARATION"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    datasets = json.loads(printed.stdout)["catalogue"]["datasets"]
    assert [d["key"] for d in datasets] == ["daily", "live"]
    assert [d["modes"] for d in datasets] == [["pull", "push"], ["pull", "stream"]]
