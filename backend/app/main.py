"""AuraSync FastAPI application."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import re
import sys
import time
from collections import deque
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator

from .config import (
    AppSettings,
    GroupInput,
    MappingInput,
    StrictModel,
    WebhookPayload,
    WebhookPreset,
    load_runtime,
    normalise_hex,
)
from .db import Database
from .state import AppState
from .telemetry import TelemetryService

LOGGER = logging.getLogger("aurasync")
EVENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
COLOUR_NAMES = (
    (75.0, "Cyan", "🟦"),
    (50.0, "Green", "🟩"),
    (25.0, "Amber", "🟨"),
    (15.0, "Orange", "🟧"),
    (5.0, "Red", "🟥"),
    (0.0, "Critical red", "🔴"),
)


class StaticTestRequest(StrictModel):
    color: str = "#22d3ee"
    duration: float = Field(default=5.0, ge=0.5, le=300.0)
    brightness: int = Field(default=100, ge=0, le=100)
    effect: Literal["solid", "flash", "pulse", "breathe", "rainbow"] = "solid"
    target: Literal["managed", "all"] = "all"

    @field_validator("color")
    @classmethod
    def _colour(cls, value: str) -> str:
        return normalise_hex(value)


class MappingTestRequest(StrictModel):
    duration: float = Field(default=8.0, ge=0.5, le=300.0)


class ManualControlRequest(StrictModel):
    target_type: Literal["all", "zone", "device", "group"]
    target_id: str = Field(default="", max_length=200)
    color: str = "#ffffff"
    brightness: int = Field(default=100, ge=0, le=100)
    effect: Literal["solid", "flash", "pulse", "breathe", "rainbow"] = "solid"
    duration: float = Field(default=3600.0, ge=0.5, le=86400.0)

    @field_validator("color")
    @classmethod
    def _colour(cls, value: str) -> str:
        return normalise_hex(value)


class TokenResponse(StrictModel):
    token: str


class Context:
    def __init__(
        self,
        runtime: Any,
        db: Database,
        state: AppState,
        telemetry: TelemetryService,
        renderer: Any,
    ) -> None:
        self.runtime = runtime
        self.db = db
        self.state = state
        self.telemetry = telemetry
        self.renderer = renderer
        self.started_at = time.time()


class SlidingWindowLimiter:
    def __init__(self, limit: int = 120, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._events: dict[str, deque[float]] = {}
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        async with self._lock:
            bucket = self._events.setdefault(key, deque())
            while bucket and now - bucket[0] > self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            if len(self._events) > 4096:
                cutoff = now - self.window
                self._events = {
                    event_key: values
                    for event_key, values in self._events.items()
                    if values and values[-1] > cutoff
                }
            return True


limiter = SlidingWindowLimiter()


def _ctx(request: Request) -> Context:
    context = getattr(request.app.state, "ctx", None)
    if context is None:
        raise HTTPException(status_code=503, detail="AuraSync is still starting")
    return context


def _source_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else "unknown"


def _colour_status(free_percent: float) -> tuple[str, str]:
    for threshold, name, emoji in COLOUR_NAMES:
        if free_percent > threshold:
            return name, emoji
    return "Critical red", "🔴"


def _primary_storage(context: Context) -> tuple[dict[str, Any] | None, Any | None]:
    settings, _groups, mappings = context.state.config_snapshot()
    telemetry = context.state.telemetry()
    storage_map = telemetry.get("storage") or {}
    storage_mapping = next(
        (mapping for mapping in mappings if mapping.enabled and mapping.mode == "storage"),
        None,
    )
    if storage_mapping is not None:
        path = storage_mapping.params.path or settings.storage_path or "/"
    else:
        path = settings.storage_path or "/"
    entry = storage_map.get(path)
    if not entry and storage_map:
        path = next(iter(storage_map))
        entry = storage_map[path]
    return (dict(entry) if entry else None), storage_mapping


def _age_label(timestamp: str | None) -> str:
    if not timestamp:
        return "never"
    try:
        parsed = datetime.fromisoformat(timestamp)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        delta = max(0, int((datetime.now(UTC) - parsed).total_seconds()))
    except ValueError:
        return "unknown"
    if delta < 10:
        return "just now"
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _mode_label(context: Context) -> tuple[str, str | None]:
    _settings, _groups, mappings = context.state.config_snapshot()
    enabled = [mapping for mapping in mappings if mapping.enabled]
    if not enabled:
        return "Idle", None
    primary = next((mapping for mapping in enabled if mapping.mode == "storage"), enabled[0])
    label = {
        "storage": "Storage gauge",
        "temp_cpu": "CPU temperature",
        "temp_gpu": "GPU temperature",
        "cpu_load": "CPU load",
        "ram_load": "RAM load",
        "static": "Static colour",
        "off": "Off",
    }[primary.mode]
    return label, primary.id


def _public_mapping(mapping: Any, devices: list[dict[str, Any]], groups: list[Any]) -> dict[str, Any]:
    payload = mapping.model_dump()
    zone_ids = {
        zone["id"] for device in devices for zone in device.get("zones", [])
    }
    device_keys = {device["key"] for device in devices}
    if mapping.target_type == "zone":
        exists = mapping.target_id in zone_ids
        label = mapping.target_id
        for device in devices:
            for zone in device.get("zones", []):
                if zone["id"] == mapping.target_id:
                    label = f"{device['name']} · {zone['name']}"
                    break
    elif mapping.target_type == "device":
        exists = mapping.target_id in device_keys
        label = next(
            (device["name"] for device in devices if device["key"] == mapping.target_id),
            mapping.target_id,
        )
    else:
        group = next((item for item in groups if item.id == mapping.target_id), None)
        exists = group is not None
        label = group.name if group else mapping.target_id
    return {**payload, "target_exists": exists, "target_label": label}


def _group_public(group: Any, devices: list[dict[str, Any]]) -> dict[str, Any]:
    zone_devices: dict[str, str] = {}
    for device in devices:
        for zone in device.get("zones", []):
            zone_devices[zone["id"]] = device["name"]
    return {
        **group.model_dump(),
        "zone_count": len(group.zones),
        "device_names": sorted({zone_devices[zone] for zone in group.zones if zone in zone_devices}),
        "missing_zones": [zone for zone in group.zones if zone not in zone_devices],
    }


async def _diagnostics(context: Context) -> dict[str, Any]:
    if context.state.diagnostics_age() > 20:
        diagnostics = await asyncio.to_thread(context.telemetry.diagnostics)
        context.state.set_diagnostics(diagnostics)
    return context.state.diagnostics()


def _check_storage_path(context: Context, path: str) -> None:
    try:
        context.telemetry.storage_usage(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Storage path is not readable: {exc}") from exc


def _validate_mapping(context: Context, payload: MappingInput, exclude_id: str | None = None) -> None:
    devices = context.state.devices()
    groups = context.state.groups()
    zone_ids = {zone["id"] for device in devices for zone in device.get("zones", [])}
    device_keys = {device["key"] for device in devices}
    if payload.target_type == "zone" and payload.target_id not in zone_ids:
        raise HTTPException(status_code=422, detail="The selected LED zone is no longer available")
    if payload.target_type == "device" and payload.target_id not in device_keys:
        raise HTTPException(status_code=422, detail="The selected device is no longer available")
    if payload.target_type == "group" and not any(group.id == payload.target_id for group in groups):
        raise HTTPException(status_code=422, detail="The selected group no longer exists")
    existing = context.db.find_mapping(payload.target_type, payload.target_id)
    if existing and existing.id != exclude_id:
        raise HTTPException(status_code=409, detail="That target already has a mapping")
    if payload.mode == "storage" and payload.params.path:
        _check_storage_path(context, payload.params.path)
    if payload.params.layout not in {"mirror", "extend"}:
        raise HTTPException(status_code=422, detail="Invalid layout")


def _check_group_overlap(context: Context, zones: list[str], group_id: str | None = None) -> None:
    for group in context.db.list_groups():
        if group.id == group_id:
            continue
        overlap = set(zones) & set(group.zones)
        if overlap:
            raise HTTPException(
                status_code=409,
                detail=f"Zone already belongs to group '{group.name}'",
            )


def _webhook_auth(context: Context, request: Request) -> None:
    header = request.headers.get("authorization", "")
    offered = ""
    if header.lower().startswith("bearer "):
        offered = header[7:].strip()
    if not offered:
        offered = request.headers.get("x-aura-token", "").strip()
    expected = context.state.webhook_token
    if not expected or not offered or not hmac.compare_digest(offered, expected):
        raise HTTPException(
            status_code=401,
            detail="A valid webhook bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _merge_webhook_payload(
    context: Context, event: str, raw: dict[str, Any] | None
) -> WebhookPayload:
    raw = raw or {}
    preset = context.db.get_preset(event)
    if not raw and not preset:
        raise HTTPException(
            status_code=422,
            detail="No preset exists for this event; send a JSON body with at least a colour",
        )
    base: dict[str, Any] = {}
    if preset:
        base = {
            "color": preset.color,
            "effect": preset.effect,
            "duration": preset.duration,
            "brightness": preset.brightness,
        }
    base.update({key: value for key, value in raw.items() if value is not None})
    if not base.get("color"):
        base["color"] = "#22d3ee"
    try:
        return WebhookPayload.model_validate(base)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _webhook_widget(context: Context) -> dict[str, Any]:
    hardware = context.state.hardware()
    storage, _mapping = _primary_storage(context)
    mode_label, _mode_id = _mode_label(context)
    devices = context.state.devices()
    count = int(hardware.get("device_count") or len(devices))
    last = context.db.last_webhook()

    if storage:
        used = float(storage.get("used_percent", 0.0))
        free = float(storage.get("free_percent", 100.0 - used))
        free_human = storage.get("free_human", "—")
    else:
        used, free, free_human = 0.0, 100.0, "—"
    _colour_name, emoji = _colour_status(free)

    items = [
        {
            "emoji": emoji,
            "text": f"{mode_label} · {count} device{'s' if count != 1 else ''}",
        },
        {
            "emoji": "💾",
            "text": f"{used:.0f}% used · {free_human} free",
        },
    ]
    if last:
        suffix = f" · {_age_label(last.get('created_at'))}"
        items.append({"emoji": "⚡", "text": f"{last.get('event')}{suffix}"})
    else:
        items.append({"emoji": "⚡", "text": "No webhooks yet"})
    return {
        "type": "list-emoji",
        "refresh": "5s",
        "link": "",
        "count": str(count),
        "items": items,
    }


async def _storage_widget(context: Context) -> dict[str, Any]:
    storage, _mapping = _primary_storage(context)
    if storage:
        used = float(storage.get("used_percent", 0.0))
        free = float(storage.get("free_percent", 100.0 - used))
        free_human = storage.get("free_human", "—")
        path = storage.get("path", "/")
    else:
        used, free, free_human, path = 0.0, 100.0, "—", "unavailable"
    colour_name, emoji = _colour_status(free)
    return {
        "type": "text-with-progress",
        "refresh": "5s",
        "link": "",
        "title": "RGB storage gauge",
        "text": f"{used:.0f}%",
        "subtext": f"{free_human} free",
        "progressLabel": f"{emoji} {colour_name} · {path}",
        "progress": round(max(0.0, min(1.0, used / 100.0)), 3),
    }


def _security_headers(response: Response) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = load_runtime()
    runtime.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, runtime.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
        force=True,
    )
    db = Database(runtime.db_path)
    token = runtime.webhook_token or db.get_or_create_webhook_token()
    state = AppState(db, token)
    telemetry = TelemetryService(runtime, state.settings, state.storage_paths)

    # Populate the first frame of telemetry before serving requests.
    try:
        initial = await asyncio.to_thread(telemetry.collect)
        state.set_telemetry(initial.to_dict())
    except Exception:
        LOGGER.exception("Initial telemetry collection failed")

    # Imported lazily so unit tests can import renderering helpers without
    # starting a thread.
    from .renderer import start_renderer

    renderer = start_renderer(
        state,
        runtime.openrgb_host,
        runtime.openrgb_port,
        runtime.openrgb_client_name,
    )
    context = Context(runtime, db, state, telemetry, renderer)
    app.state.ctx = context

    stop = asyncio.Event()
    tasks = [asyncio.create_task(telemetry.run(stop), name="aurasync-telemetry")]

    async def diagnostics_loop() -> None:
        while not stop.is_set():
            try:
                diagnostics = await asyncio.to_thread(telemetry.diagnostics)
                state.set_diagnostics(diagnostics)
            except Exception:
                LOGGER.exception("Host diagnostics collection failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=25)
            except TimeoutError:
                pass

    tasks.append(asyncio.create_task(diagnostics_loop(), name="aurasync-diagnostics"))
    LOGGER.info("AuraSync %s started (OpenRGB %s:%s)", runtime.version, runtime.openrgb_host, runtime.openrgb_port)
    try:
        yield
    finally:
        stop.set()
        renderer.stop()
        await asyncio.to_thread(renderer.join, 5.0)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        db.close()
        app.state.ctx = None
        LOGGER.info("AuraSync stopped")


app = FastAPI(
    title="AuraSync",
    version="1.0.0",
    description="Telemetry-driven RGB lighting for umbrelOS",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)


@app.middleware("http")
async def request_guard(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 64 * 1024:
                return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
    response = await call_next(request)
    _security_headers(response)
    return response


# --------------------------------------------------------------------------- basics


@app.get("/api/health")
async def health() -> dict[str, Any]:
    context = getattr(app.state, "ctx", None)
    return {
        "ok": context is not None,
        "service": "aurasync",
        "version": context.runtime.version if context else None,
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
    }


@app.get("/api/bootstrap")
async def bootstrap(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    devices = context.state.devices()
    groups = context.state.groups()
    mappings = context.state.mappings()
    settings = context.state.public_settings()
    diagnostics = await _diagnostics(context)
    mounts = await asyncio.to_thread(context.telemetry.mounts)
    storage, _mapping = _primary_storage(context)
    mode_label, _mode_id = _mode_label(context)
    last = context.db.last_webhook()
    logs = context.db.list_webhook_logs(limit=80)
    presets = context.db.list_presets()
    sensors = context.state.sensors() or context.telemetry.sensors()
    return {
        "server": {
            "name": "AuraSync",
            "version": context.runtime.version,
            "started_at": context.started_at,
            "timezone": context.runtime.tz,
        },
        "settings": settings,
        "night_active": context.state.night_active(),
        "devices": devices,
        "groups": [_group_public(group, devices) for group in groups],
        "mappings": [_public_mapping(mapping, devices, groups) for mapping in mappings],
        "telemetry": context.state.telemetry(),
        "sensors": sensors,
        "mounts": mounts,
        "diagnostics": diagnostics,
        "presets": [preset.model_dump() for preset in presets],
        "logs": logs,
        "webhook": {
            "token": context.state.webhook_token,
            "endpoint": "/api/webhook/{event}",
            "auth": "Authorization: Bearer <token>",
        },
        "summary": {
            "mode": mode_label,
            "storage": storage,
            "last_webhook": last,
            "device_count": len(devices),
        },
        "widgets": {
            "status": "/widgets/status",
            "storage": "/widgets/storage",
        },
    }


@app.get("/api/live")
async def live(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    diagnostics = await _diagnostics(context)
    settings = context.state.public_settings()
    devices = context.state.devices()
    storage, _mapping = _primary_storage(context)
    mode_label, mode_id = _mode_label(context)
    last = context.db.last_webhook()
    frame = context.state.frame_info()
    overlays = [overlay.to_dict() for overlay in context.state.active_overlays()]
    return {
        "now": time.time(),
        "hardware": context.state.hardware(),
        "telemetry": context.state.telemetry(),
        "settings": settings,
        "night_active": context.state.night_active(),
        "overlays": overlays,
        "zone_colors": context.state.zone_colors(),
        "frame": frame,
        "last_webhook": last,
        "summary": {
            "mode": mode_label,
            "mode_id": mode_id,
            "storage": storage,
            "device_count": len(devices),
            "zone_count": sum(len(device.get("zones", [])) for device in devices),
            "led_count": sum(int(device.get("led_count", 0)) for device in devices),
        },
        "diagnostics": diagnostics,
    }


@app.get("/api/webhook/token")
async def webhook_token(request: Request) -> TokenResponse:
    context = _ctx(request)
    return TokenResponse(token=context.state.webhook_token)


@app.post("/api/devices/rescan")
async def rescan_devices(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    context.renderer.request_rescan()
    return {"ok": True, "message": "OpenRGB rescan requested"}


# -------------------------------------------------------------------------- settings


@app.put("/api/settings")
async def update_settings(request: Request, payload: AppSettings) -> dict[str, Any]:
    context = _ctx(request)
    _check_storage_path(context, payload.storage_path)
    context.db.save_settings(payload)
    context.state.reload_config()
    context.telemetry.request_refresh()
    return {"ok": True, "settings": context.state.public_settings()}


# ---------------------------------------------------------------------------- groups


@app.post("/api/groups")
async def create_group(request: Request, payload: GroupInput) -> dict[str, Any]:
    context = _ctx(request)
    zone_ids = {
        zone["id"] for device in context.state.devices() for zone in device.get("zones", [])
    }
    unknown = [zone for zone in payload.zones if zone not in zone_ids]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown zones: {', '.join(unknown[:4])}")
    _check_group_overlap(context, payload.zones)
    group = context.db.create_group(payload.name, payload.zones)
    context.state.reload_config()
    return {"ok": True, "group": _group_public(group, context.state.devices())}


@app.put("/api/groups/{group_id}")
async def update_group(request: Request, group_id: str, payload: GroupInput) -> dict[str, Any]:
    context = _ctx(request)
    zone_ids = {
        zone["id"] for device in context.state.devices() for zone in device.get("zones", [])
    }
    unknown = [zone for zone in payload.zones if zone not in zone_ids]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown zones: {', '.join(unknown[:4])}")
    _check_group_overlap(context, payload.zones, group_id)
    group = context.db.update_group(group_id, payload.name, payload.zones)
    if group is None:
        raise HTTPException(status_code=404, detail="Group not found")
    context.state.reload_config()
    return {"ok": True, "group": _group_public(group, context.state.devices())}


@app.delete("/api/groups/{group_id}")
async def delete_group(request: Request, group_id: str) -> dict[str, Any]:
    context = _ctx(request)
    if not context.db.delete_group(group_id):
        raise HTTPException(status_code=404, detail="Group not found")
    context.state.reload_config()
    return {"ok": True}


# -------------------------------------------------------------------------- mappings


@app.post("/api/mappings")
async def create_mapping(request: Request, payload: MappingInput) -> dict[str, Any]:
    context = _ctx(request)
    _validate_mapping(context, payload)
    mapping = context.db.create_mapping(payload)
    context.state.reload_config()
    return {
        "ok": True,
        "mapping": _public_mapping(mapping, context.state.devices(), context.state.groups()),
    }


@app.put("/api/mappings/{mapping_id}")
async def update_mapping(
    request: Request, mapping_id: str, payload: MappingInput
) -> dict[str, Any]:
    context = _ctx(request)
    if context.db.get_mapping(mapping_id) is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    _validate_mapping(context, payload, exclude_id=mapping_id)
    mapping = context.db.update_mapping(mapping_id, payload)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    context.state.reload_config()
    return {
        "ok": True,
        "mapping": _public_mapping(mapping, context.state.devices(), context.state.groups()),
    }


@app.delete("/api/mappings/{mapping_id}")
async def delete_mapping(request: Request, mapping_id: str) -> dict[str, Any]:
    context = _ctx(request)
    if not context.db.delete_mapping(mapping_id):
        raise HTTPException(status_code=404, detail="Mapping not found")
    context.state.reload_config()
    return {"ok": True}


@app.post("/api/mappings/{mapping_id}/test")
async def test_mapping(
    request: Request, mapping_id: str, payload: MappingTestRequest
) -> dict[str, Any]:
    context = _ctx(request)
    mapping = context.db.get_mapping(mapping_id)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    overlay = AppState.new_overlay(
        kind="mapping-test",
        effect="solid",
        duration=payload.duration,
        brightness=mapping.params.brightness,
        priority=90,
        color=mapping.params.color,
        mapping=mapping,
        message=f"Testing {mapping.mode}",
    )
    context.state.add_overlay(overlay)
    return {"ok": True, "overlay": overlay.to_dict()}


# ------------------------------------------------------------------------------ tests


@app.post("/api/test")
async def test_static(request: Request, payload: StaticTestRequest) -> dict[str, Any]:
    context = _ctx(request)
    overlay = AppState.new_overlay(
        kind="static-test",
        effect=payload.effect,
        duration=payload.duration,
        brightness=payload.brightness,
        priority=90,
        color=payload.color,
        target_scope=payload.target,
        message="Colour test",
    )
    context.state.add_overlay(overlay)
    return {"ok": True, "overlay": overlay.to_dict()}


@app.post("/api/control")
async def manual_control(request: Request, payload: ManualControlRequest) -> dict[str, Any]:
    context = _ctx(request)
    devices = context.state.devices()
    groups = context.state.groups()
    all_zone_ids = [zone["id"] for device in devices for zone in device.get("zones", [])]
    if payload.target_type == "all":
        target_ids = all_zone_ids
    elif payload.target_type == "zone":
        target_ids = [payload.target_id] if payload.target_id in all_zone_ids else []
    elif payload.target_type == "device":
        target_ids = [
            zone["id"]
            for device in devices
            if device["key"] == payload.target_id
            for zone in device.get("zones", [])
        ]
    else:
        group = next((item for item in groups if item.id == payload.target_id), None)
        target_ids = [zone_id for zone_id in (group.zones if group else []) if zone_id in all_zone_ids]
    if not target_ids:
        raise HTTPException(status_code=422, detail="The selected target has no addressable LEDs")
    overlay = AppState.new_overlay(
        kind="manual",
        effect=payload.effect,
        duration=payload.duration,
        brightness=payload.brightness,
        priority=80,
        color=payload.color,
        message="Manual control",
        target_scope="all",
        target_ids=target_ids,
    )
    context.state.add_overlay(overlay)
    return {"ok": True, "overlay": overlay.to_dict()}


@app.delete("/api/overlays")
async def clear_overlays(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    return {"ok": True, "cleared": context.state.clear_overlays()}


# --------------------------------------------------------------------------- webhooks


@app.post("/api/webhook/{event}")
async def receive_webhook(request: Request, event: str) -> dict[str, Any]:
    context = _ctx(request)
    if not EVENT_RE.fullmatch(event):
        raise HTTPException(status_code=422, detail="Invalid event name")
    source = _source_ip(request)
    if not await limiter.allow(source):
        context.db.log_webhook(event, "rate_limited", source)
        raise HTTPException(status_code=429, detail="Too many webhook calls; slow down")
    _webhook_auth(context, request)
    raw: dict[str, Any] | None = None
    body_bytes = await request.body()
    if body_bytes.strip():
        if len(body_bytes) > 64 * 1024:
            raise HTTPException(status_code=413, detail="Webhook body is too large")
        try:
            body = json.loads(body_bytes)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Body must be valid JSON") from exc
        if body is not None and not isinstance(body, dict):
            raise HTTPException(status_code=422, detail="Body must be a JSON object")
        raw = body
    payload = _merge_webhook_payload(context, event, raw)
    overlay = AppState.new_overlay(
        kind="webhook",
        effect=payload.effect,
        duration=payload.duration,
        brightness=payload.brightness,
        priority=payload.priority,
        color=payload.color or "#22d3ee",
        event_name=event,
        message=payload.message,
        target_scope=payload.target,
    )
    context.state.add_overlay(overlay)
    context.db.log_webhook(
        event,
        "applied",
        source,
        {
            "color": payload.color,
            "effect": payload.effect,
            "duration": payload.duration,
            "priority": payload.priority,
            "message": payload.message,
        },
    )
    return {
        "ok": True,
        "event": event,
        "overlay": overlay.to_dict(),
        "message": "Lighting override applied; telemetry resumes automatically",
    }


@app.get("/api/webhooks")
async def list_webhooks(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    return {
        "token": context.state.webhook_token,
        "logs": context.db.list_webhook_logs(limit=200),
        "presets": [preset.model_dump() for preset in context.db.list_presets()],
    }


@app.post("/api/webhooks/presets")
async def save_preset(request: Request, payload: WebhookPreset) -> dict[str, Any]:
    context = _ctx(request)
    preset = context.db.save_preset(payload)
    return {"ok": True, "preset": preset.model_dump()}


@app.delete("/api/webhooks/presets/{event}")
async def delete_preset(request: Request, event: str) -> dict[str, Any]:
    context = _ctx(request)
    if not context.db.delete_preset(event):
        raise HTTPException(status_code=404, detail="Preset not found")
    return {"ok": True}


@app.delete("/api/webhooks/logs")
async def clear_webhook_logs(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    context.db.clear_webhook_logs()
    return {"ok": True}


@app.get("/api/diagnostics")
async def diagnostics(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    return await _diagnostics(context)


# ----------------------------------------------------------------------------- widgets


@app.get("/widgets/status")
async def widget_status(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    return await _webhook_widget(context)


@app.get("/widgets/storage")
async def widget_storage(request: Request) -> dict[str, Any]:
    context = _ctx(request)
    return await _storage_widget(context)


@app.get("/")
async def root() -> dict[str, Any]:
    return {
        "service": "AuraSync",
        "ui": "A static dashboard is served by the web container in the umbrelOS package.",
        "health": "/api/health",
        "widgets": ["/widgets/status", "/widgets/storage"],
    }
