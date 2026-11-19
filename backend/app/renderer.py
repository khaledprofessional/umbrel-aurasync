"""LED rendering engine and the background hardware writer thread."""

from __future__ import annotations

import copy
import logging
import math
import threading
import time
from dataclasses import dataclass
from typing import Any

from .config import (
    RGB,
    AppSettings,
    Group,
    Mapping,
    MappingParams,
    clamp,
    hex_to_rgb,
    hsv_to_rgb,
)
from .openrgb import OpenRGBClient, OpenRGBError
from .state import AppState, Overlay

LOGGER = logging.getLogger(__name__)

BLACK: RGB = (0, 0, 0)

STORAGE_STOPS: tuple[tuple[float, RGB], ...] = (
    (100.0, (34, 211, 238)),   # cyan — plenty of free space
    (50.0, (52, 211, 153)),    # green
    (25.0, (251, 191, 36)),    # amber
    (15.0, (249, 115, 22)),    # orange
    (5.0, (239, 68, 68)),      # red
    (0.0, (220, 38, 38)),      # deep red
)

TEMPERATURE_STOPS: tuple[tuple[float, RGB], ...] = (
    (0.0, (59, 130, 246)),     # cool blue
    (0.25, (34, 211, 238)),    # cyan
    (0.5, (34, 197, 94)),      # green
    (0.72, (245, 158, 11)),    # amber
    (1.0, (239, 68, 68)),      # hot red
)


@dataclass(slots=True)
class ZoneRef:
    id: str
    device_key: str
    device_index: int
    zone_index: int
    name: str
    led_count: int


# --------------------------------------------------------------------------- colour


def mix(first: RGB, second: RGB, amount: float) -> RGB:
    amount = clamp(amount, 0.0, 1.0)
    return (
        round(first[0] + (second[0] - first[0]) * amount),
        round(first[1] + (second[1] - first[1]) * amount),
        round(first[2] + (second[2] - first[2]) * amount),
    )


def scale(colour: RGB, factor: float) -> RGB:
    factor = clamp(factor, 0.0, 1.0)
    return (round(colour[0] * factor), round(colour[1] * factor), round(colour[2] * factor))


def ramp(stops: tuple[tuple[float, RGB], ...], value: float) -> RGB:
    """Interpolate a descending-stop ramp continuously (no hard threshold jumps)."""

    value = clamp(value, stops[-1][0], stops[0][0])
    for index in range(len(stops) - 1):
        high_value, high_colour = stops[index]
        low_value, low_colour = stops[index + 1]
        if high_value >= value >= low_value:
            span = high_value - low_value
            if span <= 0:
                return low_colour
            return mix(low_colour, high_colour, (value - low_value) / span)
    return stops[-1][1]


def storage_colour(free_percent: float) -> RGB:
    return ramp(STORAGE_STOPS, free_percent)


def temperature_colour(temp_c: float, low: float, high: float) -> RGB:
    span = max(0.1, high - low)
    normalised = clamp((temp_c - low) / span, 0.0, 1.0)
    ascending = tuple((ratio, colour) for ratio, colour in TEMPERATURE_STOPS)
    for index in range(len(ascending) - 1):
        low_ratio, low_colour = ascending[index]
        high_ratio, high_colour = ascending[index + 1]
        if low_ratio <= normalised <= high_ratio:
            span_ratio = high_ratio - low_ratio
            return mix(low_colour, high_colour, (normalised - low_ratio) / span_ratio)
    return ascending[-1][1]


def effect_amount(effect: str, now: float, speed: float = 1.0) -> float:
    if effect == "solid":
        return 1.0
    if effect == "flash":
        phase = (now * 2.4 * speed) % 1.0
        return 1.0 if phase < 0.68 else 0.04
    if effect == "pulse":
        return 0.18 + 0.82 * (0.5 + 0.5 * math.sin(now * math.tau * 0.9 * speed))
    if effect == "breathe":
        return 0.08 + 0.92 * (0.5 - 0.5 * math.cos(now * math.tau * 0.22 * speed))
    return 1.0


def _unlit(params: MappingParams, status: RGB) -> RGB:
    if params.show_unlit:
        return scale(status, 0.045)
    return BLACK


def _fill(
    count: int,
    fraction: float,
    colour: RGB,
    params: MappingParams,
    critical_factor: float = 1.0,
    master: float = 1.0,
) -> list[RGB]:
    """Fill from index 0 toward index n-1, with a fractional final LED."""

    count = max(0, count)
    fraction = clamp(fraction, 0.0, 1.0)
    units = fraction * count
    full = math.floor(units)
    remainder = units - full
    brightness = master * params.brightness / 100.0
    output: list[RGB] = []
    for index in range(count):
        if index < full:
            output.append(scale(colour, critical_factor * brightness))
        elif index == full and remainder > 0.001:
            output.append(scale(colour, critical_factor * brightness * remainder))
        else:
            output.append(_unlit(params, colour))
    if params.reverse:
        output.reverse()
    return output


# ------------------------------------------------------------------------- rendering


def zone_from_dict(device: dict[str, Any], zone: dict[str, Any]) -> ZoneRef:
    return ZoneRef(
        id=zone["id"],
        device_key=device["key"],
        device_index=int(device["index"]),
        zone_index=int(zone["index"]),
        name=zone.get("name") or "Zone",
        led_count=int(zone.get("led_count") or 0),
    )


def all_zones(devices: list[dict[str, Any]]) -> dict[str, ZoneRef]:
    result: dict[str, ZoneRef] = {}
    for device in devices:
        for zone in device.get("zones", []):
            reference = zone_from_dict(device, zone)
            if reference.led_count > 0:
                result[reference.id] = reference
    return result


def target_zones(
    target_type: str,
    target_id: str,
    devices: list[dict[str, Any]],
    groups: list[Group],
    zones: dict[str, ZoneRef],
) -> list[ZoneRef]:
    if target_type == "zone":
        zone = zones.get(target_id)
        return [zone] if zone else []
    if target_type == "device":
        return [
            zone
            for zone in zones.values()
            if zone.device_key == target_id
        ]
    if target_type == "group":
        group = next((item for item in groups if item.id == target_id), None)
        if not group:
            return []
        result = []
        for zone_id in group.zones:
            zone = zones.get(zone_id)
            if zone:
                result.append(zone)
        return result
    return []


def render_mapping_values(
    mapping: Mapping,
    led_count: int,
    telemetry: dict[str, Any],
    settings: AppSettings,
    now: float,
    master_brightness: float,
) -> list[RGB]:
    if led_count <= 0:
        return []
    params = mapping.params
    mode = mapping.mode
    effective = master_brightness * (params.brightness / 100.0)
    if mapping.enabled is False:
        return [BLACK] * led_count

    if mode == "off":
        return [BLACK] * led_count

    if mode == "static":
        return [scale(hex_to_rgb(params.color), effective)] * led_count

    if mode == "storage":
        path = params.path or settings.storage_path or "/"
        storage = (telemetry.get("storage") or {}).get(path)
        if not storage:
            # Fall back to the first storage entry if a configured mount vanished.
            entries = telemetry.get("storage") or {}
            storage = next(iter(entries.values()), None)
        used = float(storage.get("used_percent", 0.0)) if storage else 0.0
        free = 100.0 - used
        status = storage_colour(free)
        critical = 1.0
        if free < 5.0 and params.critical_pulse:
            critical = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(now * math.tau * 1.15))
        return _fill(led_count, used / 100.0, status, params, critical, master_brightness)

    if mode in {"temp_cpu", "temp_gpu"}:
        if mode == "temp_cpu":
            celsius = (telemetry.get("cpu") or {}).get("temp")
        else:
            celsius = (telemetry.get("gpu") or {}).get("temp")
        if celsius is None:
            return [scale((71, 85, 105), effective * 0.5)] * led_count
        celsius = float(celsius)
        colour = temperature_colour(celsius, params.low, params.high)
        normalised = clamp((celsius - params.low) / max(0.1, params.high - params.low), 0.0, 1.0)
        visual = params.visual
        if visual in {"bar", "fill"}:
            return _fill(led_count, normalised, colour, params, 1.0, master_brightness)
        # A subtle breathing motion makes a live temperature readable at a glance
        # while preserving the solid cool→hot gradient.
        breathe = 0.88 + 0.12 * (0.5 + 0.5 * math.sin(now * math.tau * 0.18))
        return [scale(colour, effective * breathe)] * led_count

    if mode in {"cpu_load", "ram_load"}:
        percent = (
            float((telemetry.get("cpu") or {}).get("load", 0.0))
            if mode == "cpu_load"
            else float((telemetry.get("memory") or {}).get("percent", 0.0))
        )
        percent = clamp(percent, 0.0, 100.0)
        colour = hex_to_rgb(params.color)
        visual = params.visual
        if visual == "auto":
            visual = "fill" if led_count >= 4 else "brightness"
        if visual in {"bar", "fill"}:
            return _fill(led_count, percent / 100.0, colour, params, 1.0, master_brightness)
        if visual == "breathe":
            rate = 0.35 + (percent / 100.0) * 1.55
            amount = 0.08 + 0.92 * (0.5 - 0.5 * math.cos(now * math.tau * rate * params.speed))
            return [scale(colour, effective * amount)] * led_count
        brightness = 0.18 + 0.82 * (percent / 100.0)
        return [scale(colour, effective * brightness)] * led_count

    return [BLACK] * led_count


def render_mapping_for_target(
    mapping: Mapping,
    zones: list[ZoneRef],
    telemetry: dict[str, Any],
    settings: AppSettings,
    now: float,
    master_brightness: float,
) -> dict[str, list[RGB]]:
    if not zones:
        return {}
    if mapping.params.layout == "extend" and len(zones) > 1:
        total = sum(zone.led_count for zone in zones)
        combined = render_mapping_values(mapping, total, telemetry, settings, now, master_brightness)
        output: dict[str, list[RGB]] = {}
        offset = 0
        for zone in zones:
            output[zone.id] = combined[offset : offset + zone.led_count]
            offset += zone.led_count
        return output
    return {
        zone.id: render_mapping_values(
            mapping, zone.led_count, telemetry, settings, now, master_brightness
        )
        for zone in zones
    }


def build_base_frame(
    devices: list[dict[str, Any]],
    groups: list[Group],
    mappings: list[Mapping],
    telemetry: dict[str, Any],
    settings: AppSettings,
    now: float,
) -> tuple[dict[str, list[RGB]], dict[str, Mapping]]:
    zones = all_zones(devices)
    assigned: set[str] = set()
    frame: dict[str, list[RGB]] = {}
    owners: dict[str, Mapping] = {}
    master = settings.brightness / 100.0

    ordered = [mapping for mapping in mappings if mapping.enabled]
    ordered.sort(key=lambda item: {"group": 0, "device": 1, "zone": 2}[item.target_type])

    for mapping in ordered:
        candidates = target_zones(
            mapping.target_type, mapping.target_id, devices, groups, zones
        )
        chosen = [zone for zone in candidates if zone.id not in assigned]
        if not chosen:
            continue
        rendered = render_mapping_for_target(
            mapping, chosen, telemetry, settings, now, master
        )
        for zone_id, colours in rendered.items():
            frame[zone_id] = colours
            owners[zone_id] = mapping
            assigned.add(zone_id)
    return frame, owners


def apply_night(
    frame: dict[str, list[RGB]],
    settings: AppSettings,
    night_active: bool,
) -> dict[str, list[RGB]]:
    if not night_active:
        return frame
    night = settings.night
    if night.behaviour == "off":
        return {zone_id: [BLACK] * len(colours) for zone_id, colours in frame.items()}
    colour = hex_to_rgb(night.color)
    factor = (settings.brightness / 100.0) * (night.brightness / 100.0)
    return {zone_id: [scale(colour, factor)] * len(colours) for zone_id, colours in frame.items()}


def apply_overlay(
    frame: dict[str, list[RGB]],
    overlay: Overlay,
    devices: list[dict[str, Any]],
    groups: list[Group],
    telemetry: dict[str, Any],
    settings: AppSettings,
    now: float,
) -> dict[str, list[RGB]]:
    zones = all_zones(devices)
    output = dict(frame)
    master = settings.brightness / 100.0

    if overlay.kind == "mapping-test" and overlay.mapping is not None:
        candidates = target_zones(
            overlay.mapping.target_type,
            overlay.mapping.target_id,
            devices,
            groups,
            zones,
        )
        rendered = render_mapping_for_target(
            overlay.mapping,
            candidates,
            telemetry,
            settings,
            now,
            master,
        )
        output.update(rendered)
        return output

    if overlay.target_ids is not None:
        targets = [zone_id for zone_id in overlay.target_ids if zone_id in zones]
    elif overlay.target_scope == "managed":
        targets = list(frame.keys())
        if not targets:
            targets = list(zones.keys())
    else:
        targets = list(zones.keys())

    amount = effect_amount(overlay.effect, now)
    factor = master * (overlay.brightness / 100.0) * amount
    for zone_id in targets:
        zone = zones.get(zone_id)
        if not zone:
            continue
        if overlay.effect == "rainbow":
            output[zone_id] = [
                hsv_to_rgb(
                    (index / max(1, zone.led_count)) * 360.0 + (now * 140.0),
                    0.82,
                    clamp(factor, 0.0, 1.0),
                )
                for index in range(zone.led_count)
            ]
        else:
            output[zone_id] = [scale(overlay.color, factor)] * zone.led_count
    return output


def _smooth_value(previous: float | None, target: float, alpha: float) -> float:
    if previous is None:
        return target
    return previous + (target - previous) * alpha


class LedRenderer(threading.Thread):
    """Owns the OpenRGB connection and writes frames at the configured FPS."""

    def __init__(
        self,
        state: AppState,
        host: str,
        port: int,
        client_name: str = "AuraSync",
    ) -> None:
        super().__init__(name="aurasync-renderer", daemon=True)
        self.state = state
        self._stop = threading.Event()
        self._rescan = threading.Event()
        self._client = OpenRGBClient(host, port, client_name)
        self._devices: list[dict[str, Any]] = []
        self._last_sent: dict[str, tuple[RGB, ...]] = {}
        self._previous_ids: set[str] = set()
        self._next_discovery = 0.0
        self._backoff = 2.0
        self._smooth: dict[str, float] = {}
        self._last_tick = time.monotonic()

    def request_rescan(self) -> None:
        self._rescan.set()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:  # pragma: no cover - thread orchestration
        while not self._stop.is_set():
            started = time.monotonic()
            settings, groups, mappings = self.state.config_snapshot()
            try:
                if self._rescan.is_set() or time.monotonic() >= self._next_discovery:
                    self._discover()
                frame = self._build_frame(settings, groups, mappings)
                self._write_frame(frame)
                self._publish(frame)
                self._backoff = 2.0
            except Exception as exc:  # noqa: BLE001  # keep the render thread alive
                LOGGER.warning("Render loop error: %s", exc)
                self._fail(str(exc))
                delay = min(15.0, self._backoff)
                self._backoff = min(15.0, self._backoff * 1.6)
                # A manual rescan should not have to wait out the reconnect
                # backoff after hardware or the controller container changes.
                for _ in range(max(1, int(delay * 10))):
                    if self._stop.is_set() or self._rescan.is_set():
                        break
                    self._stop.wait(0.1)
            period = 1.0 / max(1, settings.fps)
            elapsed = time.monotonic() - started
            remaining = max(0.01, period - elapsed)
            self._stop.wait(remaining)
            now = time.monotonic()
            delta = now - self._last_tick
            self._last_tick = now
            if self._client.connected:
                self.state.note_frame(1.0 / max(delta, 0.001))
        self._client.close()

    def _discover(self) -> None:
        client = self._client
        if not client.connected:
            client.connect()
        devices = client.discover()
        self._devices = [device.to_dict() for device in devices]
        self.state.set_devices(self._devices)
        self.state.set_hardware(client.status.to_dict())
        self._last_sent.clear()
        self._next_discovery = time.monotonic() + 30.0
        self._rescan.clear()
        LOGGER.info("OpenRGB discovered %d device(s)", len(devices))

    def _build_frame(
        self, settings: AppSettings, groups: list[Group], mappings: list[Mapping]
    ) -> dict[str, list[RGB]]:
        telemetry = self.state.telemetry()
        now = time.time()
        telemetry = self._smooth_telemetry(telemetry, settings)
        frame, _owners = build_base_frame(
            self._devices, groups, mappings, telemetry, settings, now
        )
        frame = apply_night(frame, settings, self.state.night_active())
        overlays = self.state.active_overlays()
        if overlays:
            frame = apply_overlay(
                frame,
                overlays[-1],
                self._devices,
                groups,
                telemetry,
                settings,
                now,
            )
        return frame

    def _smooth_telemetry(
        self, telemetry: dict[str, Any], settings: AppSettings
    ) -> dict[str, Any]:
        if not settings.smoothing:
            self._smooth.clear()
            return telemetry
        result = copy.deepcopy(telemetry)
        now = time.time()
        last = getattr(self, "_last_smooth_at", now)
        dt = max(0.001, min(1.0, now - last))
        self._last_smooth_at = now
        alpha = 1.0 - math.exp(-dt * 3.2)
        cpu = result.setdefault("cpu", {})
        if cpu.get("load") is not None:
            key = "cpu_load"
            self._smooth[key] = _smooth_value(self._smooth.get(key), float(cpu["load"]), alpha)
            cpu["load"] = self._smooth[key]
        if cpu.get("temp") is not None:
            key = "cpu_temp"
            self._smooth[key] = _smooth_value(self._smooth.get(key), float(cpu["temp"]), alpha)
            cpu["temp"] = self._smooth[key]
        memory = result.setdefault("memory", {})
        if memory.get("percent") is not None:
            key = "ram_load"
            self._smooth[key] = _smooth_value(self._smooth.get(key), float(memory["percent"]), alpha)
            memory["percent"] = self._smooth[key]
        gpu = result.get("gpu")
        if gpu and gpu.get("temp") is not None:
            key = "gpu_temp"
            self._smooth[key] = _smooth_value(self._smooth.get(key), float(gpu["temp"]), alpha)
            gpu["temp"] = self._smooth[key]
        for path, entry in (result.get("storage") or {}).items():
            key = f"storage:{path}"
            target = float(entry.get("used_percent", 0.0))
            self._smooth[key] = _smooth_value(self._smooth.get(key), target, alpha)
            entry["used_percent"] = self._smooth[key]
            entry["free_percent"] = 100.0 - self._smooth[key]
        return result

    def _write_frame(self, frame: dict[str, list[RGB]]) -> None:
        client = self._client
        if not client.connected:
            return
        zones = all_zones(self._devices)
        for zone_id, colours in frame.items():
            zone = zones.get(zone_id)
            if not zone:
                continue
            current = tuple(colours)
            if self._last_sent.get(zone_id) == current:
                continue
            client.set_zone_colours(zone.device_index, zone.zone_index, list(colours))
            self._last_sent[zone_id] = current
        # A mapping may have been removed, night may have switched everything
        # off, or a test overlay may have ended. Explicitly darken zones that
        # disappeared from the frame so the hardware does not keep stale colours.
        stale = self._previous_ids - set(frame)
        for zone_id in stale:
            zone = zones.get(zone_id)
            if zone and self._last_sent.get(zone_id) != tuple([BLACK] * zone.led_count):
                client.set_zone_colours(
                    zone.device_index, zone.zone_index, [BLACK] * zone.led_count
                )
                self._last_sent[zone_id] = tuple([BLACK] * zone.led_count)
        self._previous_ids = set(frame)
        if client.status.last_write_error:
            raise OpenRGBError(client.status.last_write_error)

    def _publish(self, frame: dict[str, list[RGB]]) -> None:
        self.state.set_zone_colors(frame)
        status = self._client.status.to_dict()
        status["connected"] = self._client.connected
        self.state.set_hardware(status)

    def _fail(self, message: str) -> None:
        self._client.mark_error(message)
        self.state.set_hardware(self._client.status.to_dict())
        self._client.close()


def start_renderer(
    state: AppState,
    runtime_host: str,
    runtime_port: int,
    client_name: str,
) -> LedRenderer:
    """Create and start the renderer with a correctly configured client."""

    renderer = LedRenderer(state, runtime_host, runtime_port, client_name)
    renderer.start()
    return renderer


class PreviewRenderer:
    """Small stateless helper used by tests and previews."""

    @staticmethod
    def storage(
        count: int,
        used_percent: float,
        params: MappingParams | None = None,
        now: float = 0.0,
    ) -> list[RGB]:
        params = params or MappingParams()
        status = storage_colour(100.0 - used_percent)
        critical = 1.0
        if 100.0 - used_percent < 5 and params.critical_pulse:
            critical = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(now * math.tau * 1.15))
        return _fill(count, used_percent / 100.0, status, params, critical, 1.0)
