# AuraSync

**Telemetry-driven RGB lighting for umbrelOS.** AuraSync turns the LEDs already inside your server into a live system display: storage fill gauges on RAM sticks, thermal gradients across fans, load meters on motherboard headers, and temporary webhook flashes from Home Assistant, Jellyfin, qBittorrent, Uptime Kuma, Frigate, and CI.

It is packaged as a complete Umbrel Community App Store with an OpenRGB hardware layer, a FastAPI control plane, a React dashboard, and native umbrelOS home-screen widgets.

```
┌──────────────────────────── umbrelOS host ────────────────────────────┐
│                                                                       │
│  /dev/i2c-*   /dev/hidraw*   /dev/bus/usb   /sys   /proc              │
│       │             │              │          │       │               │
│       └─────────────┴──────────────┴──────────┴───────┘               │
│                              │                                        │
│                    ┌─────────▼──────────┐   privileged, hardware only │
│                    │ OpenRGB SDK server │   127.0.0.1:6742 (internal) │
│                    └─────────┬──────────┘                             │
│                              │ ORGB binary protocol                   │
│                    ┌─────────▼──────────────────────────────┐         │
│                    │ AuraSync backend                    │         │
│                    │ telemetry · renderer · webhooks      │         │
│                    │ SQLite · umbrelOS widgets            │         │
│                    └─────────┬──────────────────────────────┘         │
│                              │ /api/* and /widgets/*                  │
│                    ┌─────────▼──────────┐                             │
│                    │ nginx + React UI   │  app_proxy :4287            │
│                    └────────────────────┘                             │
└───────────────────────────────────────────────────────────────────────┘
```

## What it does

- **Every LED, individually.** OpenRGB exposes controllers, zones, and LED indices. AuraSync keeps that topology and writes individual zone frames over the OpenRGB SDK.
- **Storage fill gauge (primary mode).** A multi-LED zone becomes a physical disk-usage bar. It fills bottom-to-top, uses fractional final-LED brightness, shifts continuously from cyan/green through amber and orange to red as free space disappears, and pulses when under 5% free.
- **Temperature modes.** CPU and GPU sensors produce a cool-blue → cyan → green → amber → red gradient, solid or as a fill bar.
- **CPU and RAM load.** Fill, brightness, or breathing-speed output.
- **Groups.** Combine two or four RAM sticks, or several fan rings. Set a group mapping to **mirror** the same gauge on each member or **extend** one meter across all of them.
- **Per-zone, per-device, or per-group mappings.** One target per mapping, with group > device > zone precedence for any overlap.
- **Webhook overrides.** A token-protected `POST /api/webhook/{event}` flashes, pulses, breathes, or paints rainbow for a set duration, then reverts to the active telemetry map.
- **Quiet hours.** Dim to a night colour or turn off on a daily schedule.
- **Native umbrelOS widgets.** Live status + storage gauge on the home screen.
- **Host diagnostics.** The dashboard shows whether `i2c-dev`, `i2c-i801`, or `i2c-piix4` is loaded, which I2C buses exist, and how many HID nodes are visible.

## Repository layout

```text
.
├── umbrel-app-store.yml          # Community App Store metadata
├── aura-sync/
│   ├── umbrel-app.yml            # App manifest, widgets, permissions
│   ├── docker-compose.yml        # openrgb + backend + web + app_proxy
│   ├── exports.sh                # image coordinates + derived webhook token
│   ├── icon.svg
│   └── data/                     # committed bind-mount scaffolding
├── backend/                      # FastAPI service
│   ├── app/
│   │   ├── openrgb.py            # dependency-free OpenRGB SDK client
│   │   ├── telemetry.py          # host /proc, /sys, hwmon, nvidia-smi, statvfs
│   │   ├── renderer.py           # colour maths + frame writer thread
│   │   ├── db.py                 # SQLite persistence
│   │   ├── state.py              # shared runtime state and overlays
│   │   └── main.py               # REST, webhooks, widgets
│   ├── tests/
│   └── Dockerfile
├── frontend/                     # React 19 + Vite dashboard
│   ├── src/pages/                # Overview, Devices, Mappings, Webhooks, Settings
│   ├── src/components/           # glass UI, LED strips, gauges, modals
│   ├── nginx.conf
│   └── Dockerfile
├── docker/openrgb/               # reproducible OpenRGB 1.1 headless image
├── .github/workflows/            # CI + multi-arch image publishing
├── docs/
│   ├── API.md
│   ├── ARCHITECTURE.md
│   └── HOST-SETUP.md
└── scripts/
```

## Install on umbrelOS

### 1. Publish the three images

The package is complete, but container images must live in a registry your Umbrel can pull from. The included GitHub Actions workflow builds `linux/amd64` and `linux/arm64` images and pushes them to GitHub Container Registry.

```bash
# 1. Push this repository to GitHub (for example github.com/yourname/umbrel-aurasync).
# 2. Point the app at your registry namespace.
bash scripts/configure-registry.sh yourname

# 3. Publish 1.0.0.
git add -A
git commit -m "Configure AuraSync for yourname"
git tag v1.0.0
git push origin main --tags
```

The **Publish images** workflow creates:

```text
ghcr.io/yourname/aurasync-backend:1.0.0
ghcr.io/yourname/aurasync-web:1.0.0
ghcr.io/yourname/aurasync-openrgb:1.0.0
```

After the first push, open each package in GitHub → **Packages** → **Package settings** and set visibility to **Public**. Umbrel cannot pull private packages. `exports.sh` already points at the same owner and tag.

> For an official App Store submission, pin the multi-arch image digests in `aura-sync/docker-compose.yml` after publishing:
> `docker buildx imagetools inspect ghcr.io/yourname/aurasync-backend:1.0.0`.

### 2. Add the community store

1. Open **App Store** on your umbrelOS 2.0+ device.
2. Open the **…** menu → **Community App Stores** → **Add community app store**.
3. Enter `https://github.com/aurasync/umbrel-aurasync`.
4. Open the new **AuraSync Community App Store** and install **AuraSync**.

The app opens on port **4287** (for example `http://umbrel.local:4287`). Umbrel login protects the dashboard. The webhook route is deliberately exempted so external tools can call it with their own bearer token.

### 3. One-time host preparation

Most motherboards expose SMBus only after the kernel modules are loaded. Run this once on the umbrelOS host over SSH:

```bash
# Required for RAM and many motherboard RGB controllers.
sudo modprobe i2c-dev

# Intel chipset (most common on umbrel Home / x86 servers)
sudo modprobe i2c-i801

# …or AMD chipset
# sudo modprobe i2c-piix4

# Optional but useful for verification
sudo apt-get update && sudo apt-get install -y i2c-tools
i2cdetect -l
ls -l /dev/i2c-*
```

Make it persistent across reboots:

```bash
echo i2c-dev | sudo tee /etc/modules-load.d/aurasync.conf
echo i2c-i801 | sudo tee -a /etc/modules-load.d/aurasync.conf
# use i2c-piix4 instead of i2c-i801 on AMD
```

Restart the app after loading modules. The dashboard’s **Settings → SMBus diagnostics** shows what the container can see. The OpenRGB startup log also reports every attempted module.

USB fan controllers, AIO pumps, and GPU lighting are handled through hidraw and USB HID; the privileged controller container has access automatically. No udev rules are needed inside umbrelOS.

See [docs/HOST-SETUP.md](docs/HOST-SETUP.md) for chipset names, verification, and troubleshooting.

## First configuration

1. **Devices** — confirm your controllers, zones, and LED counts. If nothing appears, use **Rescan** and review the diagnostics banner.
2. **Create a group** if you want multiple sticks or rings to act as one target.
3. **Mappings** — choose a target and a mode:
   - **Storage gauge:** pick the mount point. Leave the path empty to follow the global fill-gauge path in Settings.
   - **CPU/GPU temperature:** set the cool and hot endpoints. Auto sensor selection prefers `Package id 0` / `Tctl` / `Tdie` for CPU and `nvidia-smi` or `amdgpu` for GPU.
   - **CPU/RAM load:** choose auto, fill, brightness, or breathing.
   - **Static / Off.**
4. Use **Test** on a saved mapping for an 8-second hardware preview, or **Test lights** in the header for a quick colour flash.
5. **Settings** — set master brightness, frame rate, smoothing, sensors, timezone, and quiet hours.

The **light field** on Overview reflects the latest colours written to each zone.

### Storage gauge behaviour

| Free space | Colour |
| --- | --- |
| > 50% | Cyan → green |
| 25–50% | Amber |
| 15–25% | Orange |
| 5–15% | Red |
| < 5% | Critical red pulse (optional) |

The fill is proportional to used space. A fractional final LED is dimmed rather than rounded, so a 12-LED stick shows 6.5 LEDs worth of light. Set **Reverse fill** for sticks whose LED 0 is physically at the top.

### Group layouts

- **Mirror:** every member receives the same fill. Four 12-LED sticks all show a 50% bar.
- **Extend:** members are concatenated in the order selected. Four sticks become one 48-LED bar; the fill crosses from stick to stick.

## Webhook API

Every request needs the token shown in **Webhooks → Webhook bearer token**:

```bash
curl -X POST 'http://umbrel.local:4287/api/webhook/download_complete' \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{
    "color": "#3b82f6",
    "effect": "flash",
    "duration": 5,
    "brightness": 100,
    "target": "all"
  }'
```

- Effects: `solid`, `flash`, `pulse`, `breathe`, `rainbow`.
- Duration: 0.5–300 seconds.
- Target: `managed` (zones with mappings) or `all` (every discovered zone).
- The override is temporary. The renderer reverts automatically when it expires.
- **Presets** let you omit the body entirely: `POST /api/webhook/download_complete` uses the saved preset.
- Rate limit: 120 calls per minute per source IP.

Examples for Home Assistant, Jellyfin, qBittorrent, Uptime Kuma, Frigate, and generic CI are in [docs/API.md](docs/API.md#integration-recipes).

## umbrelOS widgets

The manifest registers two native widgets:

| Widget | Endpoint | Shows |
| --- | --- | --- |
| `rgb-status` | `GET /widgets/status` | Active mode, device count, storage fill, free-space colour, last webhook |
| `storage` | `GET /widgets/storage` | A progress bar for the primary storage gauge |

The widget endpoints are served directly by the backend on the internal Docker network; they are not proxied through Umbrel auth and expose only non-sensitive summary data.

Example `/widgets/status` response:

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

## Security model

| Boundary | Control |
| --- | --- |
| Browser UI | Umbrel app proxy login (2FA supported) |
| External webhooks | Bearer token, constant-time comparison, per-IP rate limit |
| OpenRGB container | `privileged: true` — unavoidable for arbitrary SMBus/HID topologies; no published port |
| Backend | Non-root UID 1000, read-only rootfs, all capabilities dropped, `no-new-privileges` |
| Host telemetry | `/`, `/proc`, `/sys` mounted **read-only**; storage paths resolve inside `/host/root` and cannot escape it |
| Network | Only the app proxy is published; OpenRGB SDK, backend, and widget ports stay on the internal bridge |
| Persistence | SQLite and logs under `${APP_DATA_DIR}/data`, writable only by the backend |

The OpenRGB container is the only privileged service. It has no reverse proxy, no external port, and runs exactly one process: the OpenRGB server. The application code that parses webhooks runs unprivileged in a separate container.

Hardware RGB control is inherently low-level. OpenRGB warns that reverse-engineered SMBus protocols can, in rare cases, misbehave on faulty firmware. Use supported hardware and keep backups of any vendor lighting profiles.

## Development

```bash
# Backend + frontend (Linux/macOS)
bash scripts/dev.sh

# Tests and production build
make test

# Individual
cd backend && ../.venv/bin/python -m pytest
cd frontend && pnpm run build
```

The backend works without hardware; the dashboard shows a disconnected controller and a diagnostics page. To exercise a fully populated UI, a local OpenRGB simulator is not committed, but the SDK client is covered by a fake-server test suite in `backend/tests/test_openrgb.py`.

Build the images locally:

```bash
docker build -t aurasync-backend:dev ./backend
docker build -t aurasync-web:dev ./frontend
docker build -t aurasync-openrgb:dev ./docker/openrgb
```

## Documentation

- [Architecture and render loop](docs/ARCHITECTURE.md)
- [REST, webhook, and widget API](docs/API.md)
- [Host SMBus and USB setup](docs/HOST-SETUP.md)

## Licence

MIT. OpenRGB is a separate project licensed under GPL-2.0; see <https://openrgb.org>.
