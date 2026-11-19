from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.config import (
    AppSettings,
    MappingParams,
    NightSchedule,
    hex_to_rgb,
    night_is_active,
    normalise_hex,
    rgb_to_hex,
)


def test_colour_round_trip() -> None:
    assert normalise_hex("#22D3EE") == "#22d3ee"
    assert hex_to_rgb("#22d3ee") == (34, 211, 238)
    assert rgb_to_hex((34, 211, 238)) == "#22d3ee"


def test_invalid_colour() -> None:
    with pytest.raises(ValidationError):
        MappingParams(color="cyan")
    with pytest.raises(ValidationError):
        MappingParams(color="#fff")


def test_invalid_temperature_range() -> None:
    with pytest.raises(ValidationError):
        MappingParams(low=80, high=60)


def test_night_schedule_overnight() -> None:
    schedule = NightSchedule(enabled=True, start="23:00", end="07:00")
    assert night_is_active(schedule, datetime(2026, 1, 1, 23, 30))
    assert night_is_active(schedule, datetime(2026, 1, 2, 6, 59))
    assert not night_is_active(schedule, datetime(2026, 1, 2, 12, 0))


def test_night_schedule_same_day() -> None:
    schedule = NightSchedule(enabled=True, start="01:00", end="05:00")
    assert night_is_active(schedule, datetime(2026, 1, 1, 2, 0))
    assert not night_is_active(schedule, datetime(2026, 1, 1, 6, 0))


def test_invalid_time_rejected() -> None:
    with pytest.raises(ValidationError):
        NightSchedule(start="25:99")


def test_storage_path_must_be_absolute() -> None:
    with pytest.raises(ValidationError):
        AppSettings(storage_path="mnt/data")


def test_timezone_must_be_iana() -> None:
    assert AppSettings(timezone="Europe/London").timezone == "Europe/London"
    with pytest.raises(ValidationError):
        AppSettings(timezone="Not/AZone")
