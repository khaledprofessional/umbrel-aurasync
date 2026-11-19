"""Thread-safe in-memory state shared by the API, renderer, and telemetry tasks."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from .config import (
    RGB,
    AppSettings,
    Effect,
    Group,
    Mapping,
    MappingParams,
    Mode,
    hex_to_rgb,
    night_is_active,
    rgb_to_hex,
)
from .db import Database


@dataclass(slots=True)
class Overlay:
    id: str
    kind: Literal["webhook", "static-test", "mapping-test", "manual"]
    effect: Effect
    brightness: int
    priority: int
    duration: float
    expires_at: float
    color: RGB = (34, 211, 238)
    event_name: str | None = None
    message: str | None = None
    target_scope: Literal["managed", "all"] = "managed"
    mapping: Mapping | None = None
    target_ids: tuple[str, ...] | None = None
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "effect": self.effect,
            "color": rgb_to_hex(self.color),
            "brightness": self.brightness,
            "priority": self.priority,
            "event_name": self.event_name,
            "message": self.message,
            "target_scope": self.target_scope,
            "mapping_id": self.mapping.id if self.mapping else None,
            "target_count": len(self.target_ids) if self.target_ids else None,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "remaining": max(0.0, round(self.expires_at - time.time(), 1)),
        }


class AppState:
    def __init__(self, db: Database, webhook_token: str) -> None:
        self.db = db
        self.webhook_token = webhook_token
        self._lock = threading.RLock()
        self._settings = db.get_settings()
        self._groups = db.list_groups()
        self._mappings = db.list_mappings()
        self._devices: list[dict[str, Any]] = []
        self._telemetry: dict[str, Any] = {}
        self._sensors: list[dict[str, Any]] = []
        self._hardware: dict[str, Any] = {
            "connected": False,
            "error": None,
            "server_protocol": None,
            "device_count": 0,
        }
        self._zone_colors: dict[str, list[str]] = {}
        self._overlays: list[Overlay] = []
        self._last_frame_at: float | None = None
        self._actual_fps: float = 0.0
        self._diagnostics: dict[str, Any] = {}
        self._diagnostics_at = 0.0

    # ------------------------------------------------------------------ config
    def reload_config(self) -> None:
        settings = self.db.get_settings()
        groups = self.db.list_groups()
        mappings = self.db.list_mappings()
        with self._lock:
            self._settings = settings
            self._groups = groups
            self._mappings = mappings

    def settings(self) -> AppSettings:
        with self._lock:
            return self._settings.model_copy(deep=True)

    def groups(self) -> list[Group]:
        with self._lock:
            return [group.model_copy(deep=True) for group in self._groups]

    def mappings(self) -> list[Mapping]:
        with self._lock:
            return [mapping.model_copy(deep=True) for mapping in self._mappings]

    def config_snapshot(self) -> tuple[AppSettings, list[Group], list[Mapping]]:
        with self._lock:
            return (
                self._settings.model_copy(deep=True),
                [group.model_copy(deep=True) for group in self._groups],
                [mapping.model_copy(deep=True) for mapping in self._mappings],
            )

    def storage_paths(self) -> set[str]:
        with self._lock:
            paths = {self._settings.storage_path}
            for mapping in self._mappings:
                if mapping.mode == "storage" and mapping.params.path:
                    paths.add(mapping.params.path)
        return paths

    def night_active(self) -> bool:
        settings = self.settings()
        return night_is_active(settings.night, timezone=settings.timezone)

    # ----------------------------------------------------------------- devices
    def set_devices(self, devices: list[dict[str, Any]]) -> None:
        with self._lock:
            self._devices = copy.deepcopy(devices)

    def devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._devices)

    # --------------------------------------------------------------- telemetry
    def set_telemetry(self, telemetry: dict[str, Any]) -> None:
        with self._lock:
            self._telemetry = copy.deepcopy(telemetry)
            self._sensors = copy.deepcopy(telemetry.get("sensors", []))

    def telemetry(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._telemetry)

    def sensors(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._sensors:
                return copy.deepcopy(self._sensors)
        return []

    # ---------------------------------------------------------------- hardware
    def set_hardware(self, status: dict[str, Any]) -> None:
        with self._lock:
            self._hardware = copy.deepcopy(status)

    def hardware(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._hardware)

    # -------------------------------------------------------------- LED output
    def set_zone_colors(self, colors: dict[str, list[RGB]]) -> None:
        encoded = {zone: [rgb_to_hex(colour) for colour in values] for zone, values in colors.items()}
        with self._lock:
            self._zone_colors = encoded

    def zone_colors(self) -> dict[str, list[str]]:
        with self._lock:
            return copy.deepcopy(self._zone_colors)

    def note_frame(self, fps: float) -> None:
        with self._lock:
            self._last_frame_at = time.time()
            self._actual_fps = round(fps, 1)

    def frame_info(self) -> dict[str, Any]:
        with self._lock:
            return {"last_frame_at": self._last_frame_at, "fps": self._actual_fps}

    # ---------------------------------------------------------------- overlays
    def add_overlay(self, overlay: Overlay) -> Overlay:
        with self._lock:
            now = time.time()
            self._overlays = [item for item in self._overlays if item.expires_at > now]
            self._overlays.append(overlay)
            if len(self._overlays) > 24:
                self._overlays = sorted(
                    self._overlays, key=lambda item: (item.priority, item.created_at)
                )[-24:]
        return overlay

    def active_overlays(self) -> list[Overlay]:
        now = time.time()
        with self._lock:
            self._overlays = [item for item in self._overlays if item.expires_at > now]
            return sorted(
                (copy.deepcopy(item) for item in self._overlays),
                key=lambda item: (item.priority, item.created_at),
            )

    def clear_overlays(self) -> int:
        with self._lock:
            count = len(self._overlays)
            self._overlays.clear()
        return count

    # -------------------------------------------------------------- diagnostics
    def set_diagnostics(self, diagnostics: dict[str, Any]) -> None:
        with self._lock:
            self._diagnostics = copy.deepcopy(diagnostics)
            self._diagnostics_at = time.time()

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._diagnostics)

    def diagnostics_age(self) -> float:
        with self._lock:
            return time.time() - self._diagnostics_at if self._diagnostics_at else 1e9

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def new_overlay(
        kind: Literal["webhook", "static-test", "mapping-test", "manual"],
        effect: Effect,
        duration: float,
        brightness: int,
        priority: int,
        color: str = "#22d3ee",
        event_name: str | None = None,
        message: str | None = None,
        target_scope: Literal["managed", "all"] = "managed",
        mapping: Mapping | None = None,
        target_ids: list[str] | None = None,
    ) -> Overlay:
        now = time.time()
        return Overlay(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            effect=effect,
            brightness=brightness,
            priority=priority,
            duration=duration,
            expires_at=now + duration,
            color=hex_to_rgb(color),
            event_name=event_name,
            message=message,
            target_scope=target_scope,
            mapping=mapping,
            target_ids=tuple(target_ids) if target_ids else None,
            created_at=now,
        )

    def public_settings(self) -> dict[str, Any]:
        return self.settings().model_dump()

    @staticmethod
    def overlay_descriptor(mapping: Mapping) -> dict[str, Any]:
        params: MappingParams = mapping.params
        return {
            "target_type": mapping.target_type,
            "target_id": mapping.target_id,
            "mode": mapping.mode,
            "color": params.color,
            "brightness": params.brightness,
        }

    @staticmethod
    def mode_label(mode: Mode) -> str:
        return {
            "storage": "Storage gauge",
            "temp_cpu": "CPU temperature",
            "temp_gpu": "GPU temperature",
            "cpu_load": "CPU load",
            "ram_load": "RAM load",
            "static": "Static colour",
            "off": "Off",
        }[mode]
