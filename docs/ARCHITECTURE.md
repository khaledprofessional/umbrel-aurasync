# Architecture

AuraSync is deliberately split into three processes with three different trust levels.

```
app_proxy (umbrelOS)         web (nginx + static React)
        │                            │
        │ :4287                      │ :8080
        └──────────────┬─────────────┘
                       │ /api/*, /widgets/*
                ┌──────▼─────────────┐
                │ backend            │  unprivileged, read-only rootfs
                │ FastAPI + SQLite   │  UID 1000, all caps dropped
                └──────┬─────────────┘
                       │ ORGB binary protocol (TCP 6742)
                ┌──────▼─────────────┐
                │ openrgb            │  privileged, no published ports
                │ OpenRGB SDK server  │  single process
                └──────┬─────────────┘
                       │ SMBus / I2C / USB HID
                    hardware
```

## Why this split

OpenRGB must be privileged: SMBus bus numbers and HID paths are machine-specific, and Docker cannot wildcard device nodes. Keeping it in its own container means the webhook parser, HTTP stack, and database never run with hardware privileges.

The backend receives only read-only host views:

| Mount | Purpose |
| --- | --- |
| `/:/host/root:ro` | `statvfs` for user-selected storage paths |
| `/proc:/host/proc:ro` | CPU load, memory, load average, uptime, kernel modules |
| `/sys:/host/sys:ro` | hwmon, thermal zones, I2C buses, hidraw nodes |
| `${APP_DATA_DIR}/data/backend:/data` | SQLite, only writable path |

OpenRGB receives `/sys`, `/proc`, and `/lib/modules` read-only, plus its config directory. It runs as root because access to `/dev/i2c-*`, `/dev/hidraw*`, and `/dev/bus/usb` is required; the entrypoint reports module loading and device visibility to its log.

## Backend components

### `openrgb.py` — SDK client

A dependency-free implementation of the OpenRGB binary protocol:

- 16-byte header: `"ORGB"`, device id, packet id, payload size (little-endian).
- Negotiates protocol 4. Protocol 0 is assumed if the version request times out.
- Parses device data blocks: type, strings, modes, zones, matrix maps, segments, LEDs, colours.
- Computes stable device keys from metadata; OpenRGB's enumeration index is not used as identity.
- Sends `SET_CUSTOM_MODE` when a controller has no active Direct mode.
- Sends `UPDATE_ZONELEDS` with a `data_size` prefix matching the payload.

All socket work runs in the renderer thread. The API never touches hardware.

### `telemetry.py` — host metrics

`TelemetryService` runs every two seconds in an asyncio task:

- CPU load from the delta of `/host/proc/stat`.
- Memory from `/host/proc/meminfo` (`MemAvailable`).
- Sensors from `/host/sys/class/hwmon/*/temp*_input` and thermal zones, with labels.
- NVIDIA GPUs from `nvidia-smi` when available; AMD GPUs from hwmon (`amdgpu`, `radeon`).
- Storage from `statvfs` on paths translated into `/host/root`. Symlink resolution must stay inside the host root.
- Mount discovery from `/host/proc/mounts`, filtered to real filesystems.
- Host setup diagnostics from `/host/proc/modules`, `/sys/bus/i2c/devices`, and `/sys/class/hidraw`.

The latest snapshot is immutable and copied into shared state.

### `renderer.py` — LED engine

The renderer is a daemon thread with three responsibilities:

1. Keep the OpenRGB connection alive and rediscover every 30 seconds (or on demand).
2. Build a frame from the current settings, groups, mappings, telemetry, night schedule, and overlays.
3. Write only changed zones to hardware, and darken zones that disappear from the frame.

#### Frame algorithm

```
zones = every zone reported by OpenRGB
assigned = {}
for mappings ordered group → device → zone:
    candidates = target zones not yet assigned
    for each zone:
        mirror: render the zone's LED count independently
        extend: concatenate all member LED counts, render once, slice back
if quiet hours active:
    replace base output with dim colour or black
for the highest-priority active overlay:
    replace touched zones with effect colour / rainbow
```

Only zones with a mapping (or covered by a temporary override) are written. Unmanaged hardware remains under its current controller behaviour.

#### Storage gauge

- `used_percent` from `statvfs`: `used / (used + free)`.
- Colour stops are interpolated, not switched:
  - free 100 → cyan `#22d3ee`
  - free 50 → green `#34d399`
  - free 25 → amber `#fbbf24`
  - free 15 → orange `#f97316`
  - free 5 → red `#ef4444`
  - free 0 → deep red `#dc2626`
- Fill `units = used% × LED count`. Full LEDs are at full brightness; the next LED is scaled by the fractional remainder.
- Below 5% free, an optional 1.15 Hz sine pulse modulates the entire gauge between 55% and 100%.
- `reverse` flips the final array so LED index 0 is conceptually at the top.

#### Temperature mode

Temperature is normalised between the mapping's `low` and `high` endpoints and mapped to blue → cyan → green → amber → red. Solid mode paints the zone; bar mode fills it.

#### Load mode

CPU/RAM percentages become a fill, a brightness factor, or a breathing rate. Breathing speed increases with load.

#### Overlays

`Overlay` records in `state.py` are immutable copies with an expiry. Priorities resolve competing events; the renderer always applies the highest priority, newest overlay. Webhooks apply after night mode so alerts remain visible. When an overlay expires, the next frame is built from the base mapping again.

Effects:

| Effect | Shape |
| --- | --- |
| `solid` | Constant colour |
| `flash` | 2.4 Hz square wave, 68% duty |
| `pulse` | 0.9 Hz sine |
| `breathe` | 0.22 Hz cosine |
| `rainbow` | Per-LED hue, rotating at 140°/s |

### `state.py` — shared state

`AppState` is guarded by an `RLock` and stores:

- settings, groups, and mappings (copied on read);
- discovered devices and latest telemetry;
- hardware status and per-zone colour output for the UI;
- active overlays;
- diagnostics cache;
- renderer frame metadata.

It also computes `night_active` and provides overlay factory helpers.

### `db.py` — persistence

SQLite with WAL, a 15-second busy timeout, and one connection guarded by an `RLock`.

Tables:

| Table | Contents |
| --- | --- |
| `settings` | JSON settings and generated webhook token |
| `groups` | group id, name, zone id array |
| `mappings` | target + mode + params + enabled, unique per target |
| `webhook_presets` | event, colour, effect, duration, brightness |
| `webhook_log` | last 500 deliveries, success/rate limit, source IP, detail JSON |

Deleting a group cascades its mapping in the same transaction.

### `main.py` — HTTP layer

FastAPI lifespan:

1. Load runtime configuration and logging.
2. Open SQLite and seed defaults.
3. Resolve or generate the webhook token.
4. Collect an initial telemetry sample.
5. Start the renderer thread.
6. Start telemetry and diagnostics loops.
7. On shutdown: stop renderer, cancel tasks, close SQLite.

The API validates every target against the current device list, every storage path against the host mount, and every colour/time field through Pydantic. Webhook authentication uses `hmac.compare_digest`; rate limiting uses a per-IP sliding window.

## Frontend

React 19 + Vite, no runtime CSS framework.

- `App.tsx` fetches `/api/bootstrap` once and polls `/api/live` every 2 seconds.
- Mutations call REST and then refresh the bootstrap snapshot.
- `zone_colors` from `/api/live` powers the real hardware previews, so the UI shows exactly what was written rather than a separate animation.
- The mapping editor computes a local preview with the same fill logic for unsaved drafts.
- Dark glass styling uses a single CSS design system in `src/styles.css`; focus states, reduced-motion support, and mobile layouts are included.

## umbrelOS packaging

`aura-sync/docker-compose.yml` declares:

| Service | Role |
| --- | --- |
| `openrgb` | privileged, healthchecked, internal only |
| `backend` | unprivileged, read-only, healthchecked |
| `web` | nginx static UI + same-origin API proxy |
| `app_proxy` | umbrelOS routing metadata; no image |

`exports.sh` derives:

- `APP_AURA_SYNC_IMAGE_OWNER` / `APP_AURA_SYNC_IMAGE_TAG` for image coordinates;
- `APP_AURA_SYNC_WEBHOOK_TOKEN` via `derive_entropy`, stable across updates.

The manifest declares the `GPU` permission (for NVIDIA/AMD telemetry), the app port, and two widgets. Widget endpoints use the `backend` compose service name, so they bypass the browser proxy and Umbrel auth as required by the widget system.

## Failure behaviour

| Failure | Result |
| --- | --- |
| OpenRGB unreachable | Renderer retries with backoff; UI shows disconnected; telemetry and webhooks still work |
| OpenRGB disconnects mid-frame | Socket closes, status updates, next loop reconnects |
| Device list changes | 30-second rediscovery or manual rescan; stable keys keep mappings attached |
| Invalid storage path | Mapping rejected with `422`; a saved path that later disappears falls back to the first visible mount |
| Sensor disappears | Temperature mapping shows a dim slate colour until a sensor returns |
| Webhook replay/flood | 429 after 120 calls/min from one IP; delivery log records rate limiting |
| Renderer thread crash | Exceptions are contained per loop; status surfaces the error |
| SQLite unavailable | Process fails to start rather than silently losing config |

## Design limits

- OpenRGB protocol is capped at version 4 for a compact parser. Current servers negotiate down and support per-zone updates, which is all AuraSync needs.
- Maximum 512 devices, 512 zones per device, 4,096 LEDs per device, 16 MiB packets.
- Maximum 24 in-memory overlays, 500 webhook log rows, 64 zones per group.
- Frame rate 1–20 fps; six is the default.
