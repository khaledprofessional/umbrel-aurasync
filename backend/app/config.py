"""Typed configuration, validation, and small colour/time helpers."""

from __future__ import annotations

import colorsys
import os
import re
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RGB = tuple[int, int, int]
Mode = Literal[
    "storage",
    "temp_cpu",
    "temp_gpu",
    "cpu_load",
    "ram_load",
    "static",
    "off",
]
TargetType = Literal["zone", "device", "group"]
Effect = Literal["solid", "flash", "pulse", "breathe", "rainbow"]

HEX_COLOUR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def normalise_hex(value: str) -> str:
    value = value.strip()
    if not HEX_COLOUR_RE.fullmatch(value):
        raise ValueError("colour must be a #RRGGBB hex value")
    return value.lower()


def hex_to_rgb(value: str) -> RGB:
    value = normalise_hex(value)
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def rgb_to_hex(colour: RGB) -> str:
    return "#{:02x}{:02x}{:02x}".format(*(max(0, min(255, int(c))) for c in colour))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_hhmm(value: str) -> time:
    value = value.strip()
    if not TIME_RE.fullmatch(value):
        raise ValueError("time must use 24-hour HH:MM format")
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour=hour, minute=minute)


def hsv_to_rgb(hue: float, saturation: float, value: float) -> RGB:
    red, green, blue = colorsys.hsv_to_rgb((hue % 360) / 360.0, saturation, value)
    return (round(red * 255), round(green * 255), round(blue * 255))


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NightSchedule(StrictModel):
    enabled: bool = False
    start: str = "23:00"
    end: str = "07:00"
    behaviour: Literal["dim", "off"] = "dim"
    brightness: int = Field(default=12, ge=0, le=100)
    color: str = "#0b1220"

    @field_validator("start", "end")
    @classmethod
    def _valid_time(cls, value: str) -> str:
        parse_hhmm(value)
        return value

    @field_validator("color")
    @classmethod
    def _valid_colour(cls, value: str) -> str:
        return normalise_hex(value)


class AppSettings(StrictModel):
    brightness: int = Field(default=85, ge=0, le=100)
    fps: int = Field(default=6, ge=1, le=20)
    smoothing: bool = True
    storage_path: str = "/"
    cpu_sensor: str = "auto"
    gpu_sensor: str = "auto"
    timezone: str = "Etc/UTC"
    night: NightSchedule = Field(default_factory=NightSchedule)

    @field_validator("storage_path")
    @classmethod
    def _absolute_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("storage path must be absolute")
        if "\x00" in value:
            raise ValueError("storage path contains an invalid character")
        return value or "/"

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("timezone must be a valid IANA name") from exc
        return value


class MappingParams(StrictModel):
    color: str = "#22d3ee"
    brightness: int = Field(default=100, ge=0, le=100)
    layout: Literal["mirror", "extend"] = "mirror"
    reverse: bool = False
    path: str | None = None
    show_unlit: bool = False
    low: float = Field(default=30.0, ge=0.0, le=120.0)
    high: float = Field(default=90.0, ge=1.0, le=140.0)
    visual: Literal["auto", "solid", "bar", "fill", "brightness", "breathe"] = "auto"
    speed: float = Field(default=1.0, ge=0.1, le=4.0)
    critical_pulse: bool = True

    @field_validator("color")
    @classmethod
    def _valid_colour(cls, value: str) -> str:
        return normalise_hex(value)

    @field_validator("path")
    @classmethod
    def _valid_path(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        if not value.startswith("/") or "\x00" in value:
            raise ValueError("storage path must be absolute")
        return value

    @model_validator(mode="after")
    def _valid_range(self) -> MappingParams:
        if self.high <= self.low:
            raise ValueError("temperature high must be greater than low")
        return self


class Mapping(StrictModel):
    id: str
    target_type: TargetType
    target_id: str
    mode: Mode
    params: MappingParams = Field(default_factory=MappingParams)
    enabled: bool = True


class MappingInput(StrictModel):
    target_type: TargetType
    target_id: str = Field(min_length=1, max_length=200)
    mode: Mode
    params: MappingParams = Field(default_factory=MappingParams)
    enabled: bool = True


class Group(StrictModel):
    id: str
    name: str = Field(min_length=1, max_length=64)
    zones: list[str] = Field(default_factory=list, max_length=64)
    created_at: str | None = None


class GroupInput(StrictModel):
    name: str = Field(min_length=1, max_length=64)
    zones: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("zones")
    @classmethod
    def _unique_zones(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("a zone can only be listed once per group")
        return value


class WebhookPayload(StrictModel):
    color: str | None = None
    effect: Effect = "flash"
    duration: float = Field(default=5.0, ge=0.5, le=300.0)
    brightness: int = Field(default=100, ge=0, le=100)
    priority: int = Field(default=50, ge=0, le=100)
    message: str | None = Field(default=None, max_length=240)
    target: Literal["managed", "all"] = "managed"

    @field_validator("color")
    @classmethod
    def _valid_colour(cls, value: str | None) -> str | None:
        return normalise_hex(value) if value is not None else None


class WebhookPreset(StrictModel):
    event: str = Field(min_length=1, max_length=64)
    color: str = "#22d3ee"
    effect: Effect = "flash"
    duration: float = Field(default=5.0, ge=0.5, le=300.0)
    brightness: int = Field(default=100, ge=0, le=100)

    @field_validator("event")
    @classmethod
    def _event_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
            raise ValueError("event names may contain letters, numbers, dots, underscores, and hyphens")
        return value

    @field_validator("color")
    @classmethod
    def _valid_colour(cls, value: str) -> str:
        return normalise_hex(value)


@dataclass(frozen=True)
class RuntimeConfig:
    data_dir: Path
    host_root: Path
    host_proc: Path
    host_sys: Path
    host_os_release: Path
    openrgb_host: str
    openrgb_port: int
    openrgb_client_name: str
    webhook_token: str | None
    tz: str
    log_level: str
    version: str
    db_path: Path


def load_runtime() -> RuntimeConfig:
    data_dir = Path(os.environ.get("DATA_DIR", "./data")).expanduser().resolve()
    return RuntimeConfig(
        data_dir=data_dir,
        host_root=Path(os.environ.get("HOST_ROOT", "/")).resolve(),
        host_proc=Path(os.environ.get("HOST_PROC", "/proc")).resolve(),
        host_sys=Path(os.environ.get("HOST_SYS", "/sys")).resolve(),
        host_os_release=Path(os.environ.get("HOST_OS_RELEASE", "/etc/os-release")),
        openrgb_host=os.environ.get("OPENRGB_HOST", "openrgb"),
        openrgb_port=int(os.environ.get("OPENRGB_PORT", "6742")),
        openrgb_client_name=os.environ.get("OPENRGB_CLIENT_NAME", "AuraSync"),
        webhook_token=os.environ.get("AURASYNC_WEBHOOK_TOKEN") or None,
        tz=os.environ.get("TZ", "Etc/UTC"),
        log_level=os.environ.get("AURASYNC_LOG_LEVEL", "INFO").upper(),
        version=os.environ.get("APP_VERSION", "1.0.0"),
        db_path=data_dir / "aura.db",
    )


def night_is_active(
    schedule: NightSchedule,
    now: datetime | None = None,
    timezone: str = "Etc/UTC",
) -> bool:
    if not schedule.enabled:
        return False
    if now is None:
        now = datetime.now(ZoneInfo(timezone))
    start = parse_hhmm(schedule.start)
    end = parse_hhmm(schedule.end)
    if start == end:
        return False
    current = now.time().replace(second=0, microsecond=0)
    if start < end:
        return start <= current < end
    return current >= start or current < end
