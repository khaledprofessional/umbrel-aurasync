# AuraSync API

Base URL: `http://<umbrel-host>:4287`

The dashboard and every `/api/*` route (except `/api/webhook/*`) are behind Umbrel's app proxy login. The webhook route has its own bearer token.

Interactive docs are available at `/api/docs` while signed in to Umbrel.

## Authentication

| Surface | Authentication |
| --- | --- |
| Dashboard, `/api/bootstrap`, `/api/live`, CRUD, diagnostics, widgets-through-nginx | Umbrel app proxy session |
| `POST /api/webhook/{event}` | `Authorization: Bearer <token>` or `X-Aura-Token: <token>` |
| `/widgets/status`, `/widgets/storage` | None, but only reachable on the internal Docker network |

The webhook token is generated per install by `exports.sh` through `derive_entropy`, or generated once and stored in SQLite when the env var is absent. Read it in the UI or:

```bash
curl -s http://umbrel.local:4287/api/webhooks \
  -H 'Cookie: <umbrel session cookie>' | jq -r .token
```

Unauthorized webhook requests return `401` with `WWW-Authenticate: Bearer`.

## Errors

Errors use FastAPI's standard shape:

```json
{"detail": "The selected LED zone is no longer available"}
```

| Status | Meaning |
| --- | --- |
| 400 | Malformed request or `Content-Length` |
| 401 | Missing/invalid webhook token |
| 404 | Group, mapping, or preset not found |
| 409 | Target already mapped, or a zone already belongs to another group |
| 413 | Body over 64 KiB |
| 422 | Validation error (colour, range, path, missing target) |
| 429 | Webhook rate limit (120/min per IP) |
| 503 | Process is still starting |

## Core endpoints

### `GET /api/health`

```json
{"ok": true, "service": "aurasync", "version": "1.0.0", "time": "2026-11-19T10:00:00+00:00"}
```

### `GET /api/bootstrap`

Returns a full snapshot for the dashboard: settings, devices, groups, mappings, telemetry, sensors, mounts, diagnostics, presets, logs, webhook token, and summary. This is intended for initial page load and after mutations.

### `GET /api/live`

A lightweight polling payload (the dashboard calls it every two seconds):

```json
{
  "hardware": {
    "connected": true,
    "error": null,
    "server_protocol": 4,
    "device_count": 6,
    "last_discovery": 1795085000.0,
    "last_write": 1795085001.2,
    "last_write_error": null
  },
  "telemetry": {
    "cpu": {"load": 18.2, "temp": 52.0, "sensor_id": "hwmon:coretemp:temp1", "sensor_label": "coretemp · Package id 0", "cores": 24},
    "memory": {"total": 34359738368, "used": 12884901888, "percent": 37.5},
    "gpu": {"name": "NVIDIA GeForce RTX 4070", "temp": 47.0},
    "storage": {
      "/": {"path": "/", "used_percent": 68.1, "free_percent": 31.9, "free_human": "181.3 GB"}
    }
  },
  "night_active": false,
  "overlays": [],
  "zone_colors": {"dev-abc:z0": ["#fbbf24", "#fbbf24", "#0a0b0c"]},
  "frame": {"last_frame_at": 1795085001.0, "fps": 6.0},
  "summary": {"mode": "Storage gauge", "mode_id": "0e37344e4790", "device_count": 6, "zone_count": 8, "led_count": 112}
}
```

### `POST /api/devices/rescan`

Sets a renderer flag. The background thread reconnects to OpenRGB, enumerates controllers, enters Direct mode when necessary, and publishes the new device list.

```json
{"ok": true, "message": "OpenRGB rescan requested"}
```

### `PUT /api/settings`

Body is the full settings object:

```json
{
  "brightness": 85,
  "fps": 6,
  "smoothing": true,
  "storage_path": "/",
  "cpu_sensor": "auto",
  "gpu_sensor": "auto",
  "timezone": "Europe/London",
  "night": {
    "enabled": true,
    "start": "23:00",
    "end": "07:00",
    "behaviour": "dim",
    "brightness": 12,
    "color": "#0b1220"
  }
}
```

`storage_path` must be an absolute path that exists inside the host bind mount. `behaviour` is `dim` or `off`.

## Devices and groups

### `GET /api/bootstrap` device shape

```json
{
  "key": "dev-cf18d425af2c704d",
  "index": 0,
  "name": "Aura DDR5 RAM A",
  "type": "dram",
  "vendor": "Aura Labs",
  "description": "…",
  "version": "1.0",
  "serial": "RAM-A",
  "location": "I2C: 0x50",
  "active_mode": 0,
  "modes": ["Direct", "Rainbow"],
  "led_count": 12,
  "zones": [
    {
      "id": "dev-cf18d425af2c704d:z0",
      "index": 0,
      "name": "DRAM",
      "type": "linear",
      "led_count": 12,
      "start_idx": 0,
      "matrix": null,
      "segments": [],
      "led_names": ["LED 0", "…"]
    }
  ]
}
```

Stable device keys are derived from name, vendor, serial, location, and type. They survive OpenRGB index changes.

### `POST /api/groups`

```json
{"name": "Front RAM", "zones": ["dev-a:z0", "dev-b:z0"]}
```

A zone may belong to only one group. Groups can contain up to 64 zones.

### `PUT /api/groups/{id}`

Same body as create. Replaces the zone list.

### `DELETE /api/groups/{id}`

Deletes the group and any mapping targeting it. Underlying LEDs are untouched.

## Mappings

### `POST /api/mappings`

```json
{
  "target_type": "group",
  "target_id": "f44053a7840b",
  "mode": "storage",
  "enabled": true,
  "params": {
    "color": "#22d3ee",
    "brightness": 100,
    "layout": "extend",
    "reverse": false,
    "path": null,
    "show_unlit": true,
    "low": 30,
    "high": 90,
    "visual": "auto",
    "speed": 1.0,
    "critical_pulse": true
  }
}
```

| Field | Notes |
| --- | --- |
| `target_type` | `zone`, `device`, or `group` |
| `mode` | `storage`, `temp_cpu`, `temp_gpu`, `cpu_load`, `ram_load`, `static`, `off` |
| `layout` | `mirror` or `extend`; only meaningful for multi-zone targets |
| `reverse` | Light from the far end of the zone instead of index 0 |
| `path` | Storage-only override; `null` follows global `settings.storage_path` |
| `show_unlit` | Leave a 4.5% ghost trace on unlit LEDs |
| `low` / `high` | Temperature endpoints in °C |
| `visual` | Temperature: `solid` or `bar`. Load: `auto`, `fill`, `brightness`, `breathe` |
| `critical_pulse` | Pulse the whole gauge below 5% free |

One mapping per target is allowed. Group, device, and zone mappings may coexist; for a single zone the resolution order is **group → device → zone**.

### `PUT /api/mappings/{id}`

Full replacement. To pause a mapping, send the same body with `"enabled": false`.

### `DELETE /api/mappings/{id}`

Removes the mapping. The next render sends black to any zone that disappears from the frame.

### `POST /api/mappings/{id}/test`

```json
{"duration": 8}
```

Applies the mapping as a temporary overlay at priority 90. It reverts automatically. This works even when the mapping’s normal enabled state is off, because the overlay uses a copy.

### `POST /api/test`

Quick colour test across all hardware:

```json
{
  "color": "#22d3ee",
  "effect": "flash",
  "duration": 5,
  "brightness": 100,
  "target": "all"
}
```

### `DELETE /api/overlays`

Clears every active webhook/test overlay.

## Webhooks

### `POST /api/webhook/{event}`

- `event`: 1–64 chars, letters/numbers/dots/underscores/hyphens.
- Body is optional. With no body, a saved preset with the same event name is used.
- If neither a preset nor a colour is supplied: `422`.

```json
{
  "color": "#3b82f6",
  "effect": "flash",
  "duration": 5,
  "brightness": 100,
  "priority": 50,
  "message": "Download finished",
  "target": "all"
}
```

| Field | Default | Range |
| --- | --- | --- |
| `color` | preset or `#22d3ee` | `#RRGGBB` |
| `effect` | `flash` | `solid`, `flash`, `pulse`, `breathe`, `rainbow` |
| `duration` | preset or `5` | 0.5–300 seconds |
| `brightness` | preset or `100` | 0–100 |
| `priority` | `50` | 0–100; higher wins |
| `message` | `null` | ≤240 chars |
| `target` | `managed` | `managed` (mapped zones) or `all` |

If no mappings exist yet, `managed` falls back to every discovered zone so a first webhook still has a visible effect.

Response:

```json
{
  "ok": true,
  "event": "download_complete",
  "overlay": {
    "id": "8d059d1d6bea",
    "kind": "webhook",
    "effect": "flash",
    "color": "#3b82f6",
    "brightness": 100,
    "priority": 50,
    "event_name": "download_complete",
    "target_scope": "all",
    "created_at": 1795084950.4,
    "expires_at": 1795084955.4,
    "remaining": 5.0
  },
  "message": "Lighting override applied; telemetry resumes automatically"
}
```

### Presets

```
GET    /api/webhooks                 → {token, logs, presets}
POST   /api/webhooks/presets         → save a preset
DELETE /api/webhooks/presets/{event} → remove a preset
DELETE /api/webhooks/logs            → clear delivery history
```

Preset body:

```json
{"event": "backup_complete", "color": "#22c55e", "effect": "pulse", "duration": 4, "brightness": 100}
```

Built-in presets: `download_complete`, `server_alert`, `ci_failed`, `success`.

### Integration recipes

**Home Assistant** (`configuration.yaml`):

```yaml
rest_command:
  aurasync_download:
    url: "http://umbrel.local:4287/api/webhook/download_complete"
    method: post
    headers:
      Authorization: "Bearer YOUR_TOKEN"
      Content-Type: "application/json"
    payload: '{"color":"#3b82f6","effect":"flash","duration":6}'
```

**qBittorrent** — *Options → Downloads → Run external program on torrent completion*:

```bash
curl -s -X POST "http://umbrel.local:4287/api/webhook/download_complete" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"color":"#3b82f6","effect":"flash","duration":6}'
```

**Jellyfin** (Webhooks plugin → Generic Destination):

```text
URL:              http://umbrel.local:4287/api/webhook/jellyfin.play
Authorization:    Bearer YOUR_TOKEN
Content-Type:     application/json
Template:         {"color":"#a78bfa","effect":"pulse","duration":5}
```

**Uptime Kuma** (notification webhook):

```json
{
  "url": "http://umbrel.local:4287/api/webhook/server_alert",
  "method": "POST",
  "headers": {"Authorization": "Bearer YOUR_TOKEN"},
  "body": "{\"color\":\"#ef4444\",\"effect\":\"pulse\",\"duration\":12}"
}
```

**Frigate**:

```yaml
mqtt:
  enabled: true
# Or use a simple automation that runs:
# curl -X POST .../api/webhook/frigate.detection -d '{"color":"#ef4444","effect":"flash","duration":4}'
```

**CI failure**:

```yaml
- name: Alert AuraSync
  if: failure()
  run: |
    curl -fsS -X POST "$AURASYNC_URL/api/webhook/ci_failed" \
      -H "Authorization: Bearer $AURASYNC_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"color":"#ef4444","effect":"flash","duration":8}'
```

## umbrelOS widgets

The backend returns widget JSON directly. Umbrel fetches `http://backend:8000/widgets/...` over the app’s internal compose network.

### `GET /widgets/status` — `list-emoji`

```json
{
  "type": "list-emoji",
  "refresh": "5s",
  "link": "",
  "count": "6",
  "items": [
    {"emoji": "🟦", "text": "Storage gauge · 6 devices"},
    {"emoji": "💾", "text": "68% used · 2.4 TB free"},
    {"emoji": "⚡", "text": "jellyfin.play · 12s ago"}
  ]
}
```

The first emoji is the free-space colour indicator. `count` is the discovered device count. The third row falls back to “No webhooks yet”.

### `GET /widgets/storage` — `text-with-progress`

```json
{
  "type": "text-with-progress",
  "refresh": "5s",
  "link": "",
  "title": "RGB storage gauge",
  "text": "68%",
  "subtext": "2.4 TB free",
  "progressLabel": "🟦 Cyan · /mnt/data",
  "progress": 0.68
}
```

Both widgets are read-only and unauthenticated by design. They expose no tokens, paths beyond the configured mount point, or hardware serials.

## OpenRGB protocol details

AuraSync negotiates OpenRGB SDK protocol 4, which supports per-zone updates and segments while remaining compatible with current servers (they downgrade to the negotiated level). The client:

- sends `REQUEST_PROTOCOL_VERSION` with version 4, falling back to version 0 if no response;
- sends a client name;
- requests the controller count and each controller block;
- switches controllers to Direct/custom mode once per connection;
- writes frames with `RGBCONTROLLER_UPDATEZONELEDS`.

The parser and packet builder are dependency-free and covered by a fake-server test in `backend/tests/test_openrgb.py`.
