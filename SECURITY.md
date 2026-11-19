# Security policy

## Reporting a vulnerability

Open a private security advisory on the repository or email the maintainer listed in the app manifest. Do not publish hardware-damaging or remote-code-execution details before a fix is available.

## Threat model

AuraSync sits between the internet/LAN and a privileged OpenRGB container.

- **Browser users** are authenticated by umbrelOS’s app proxy (including 2FA) before reaching the React UI or `/api/*`.
- **Webhook callers** cannot use Umbrel cookies and must present a per-install bearer token.
- **The backend** is unprivileged, has a read-only root filesystem, drops all Linux capabilities, and cannot write outside `/data`.
- **OpenRGB** is privileged and must be, because SMBus/HID device paths are not portable; it has no published port and runs only the upstream server.
- **Host telemetry** is mounted read-only; storage paths are resolved inside `/host/root` and cannot escape through `..` or symlinks.

## Secrets

| Secret | Storage | Rotation |
| --- | --- | --- |
| Webhook token | `derive_entropy` in `exports.sh`, or SQLite if the env var is absent | Change `APP_AURA_SYNC_WEBHOOK_TOKEN` and restart the app |
| OpenRGB | no authentication, internal bridge only | not exposed |
| SQLite | app data volume | delete `aura.db` to reset (configuration is lost) |

The webhook token is displayed in the authenticated dashboard. Treat the dashboard URL as sensitive if Umbrel authentication has been disabled for the app.

## Hardening notes

- Keep Umbrel login enabled for AuraSync. The public surface should remain only `/api/webhook/*`.
- If you place an additional reverse proxy in front of the app, do not expose the internal backend, OpenRGB SDK, or widget ports.
- Use a separate token per integration by editing the webhook token. A single token is currently generated per install; multiple tokens can be added by extending `webhook_presets`/auth, but are not part of 1.0.
- Review OpenRGB’s supported-device warnings before enabling unknown hardware.
- Back up `${APP_DATA_DIR}/data/backend/aura.db` if the mapping configuration matters.

## Rate limiting

Webhook calls are limited to 120 per minute per source IP. This is a denial-of-service guard, not a substitute for network isolation. If an attacker can reach the Umbrel app port, they can still consume the limit.

## Dependency posture

- Backend: FastAPI, Uvicorn, Pydantic, SQLite (standard library), and Python standard-library networking. No OpenRGB Python package is required.
- Frontend: React, Vite, lucide-react. No analytics, fonts, or third-party scripts are loaded at runtime.
- Images should be pinned by digest for an official App Store submission. The release workflow publishes multi-arch tags; see the README.
