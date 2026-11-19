#!/usr/bin/env bash
# OpenRGB container bootstrap.
#
# The container is privileged because the host's SMBus and USB HID topology
# cannot be expressed as a portable device allow-list. This script keeps the
# startup path (kernel module loading, device visibility) explicit in the
# container log and never fails merely because a module was already built in.

set -uo pipefail

log() {
    printf '[aurasync-openrgb] %s\n' "$*"
}

warn() {
    printf '[aurasync-openrgb] WARN: %s\n' "$*" >&2
}

log "starting OpenRGB SDK server on port ${OPENRGB_SERVER_PORT:-6742}"

# The host's /lib/modules is mounted read-only. `modprobe` talks to the shared
# kernel, so loading here makes the interface available to every container.
for module in i2c-dev i2c-i801 i2c-piix4 i2c-nct6793; do
    if ! command -v modprobe >/dev/null 2>&1; then
        warn "modprobe is unavailable in this image"
        break
    fi
    if modprobe "$module" 2>/tmp/modprobe-aurasync.err; then
        log "kernel module available: ${module}"
    else
        detail="$(tr '\n' ' ' </tmp/modprobe-aurasync.err | cut -c1-220)"
        warn "could not load ${module}: ${detail:-unknown error}"
    fi
done

shopt -s nullglob
i2c_devices=(/dev/i2c-*)
hid_devices=(/dev/hidraw*)
usb_buses=(/dev/bus/usb/*)

if (( ${#i2c_devices[@]} == 0 )); then
    warn "no /dev/i2c-* nodes are visible. Run 'sudo modprobe i2c-dev' on the umbrelOS host."
    warn "Intel chipsets usually need i2c-i801; AMD chipsets usually need i2c-piix4."
else
    log "visible I2C nodes: ${i2c_devices[*]}"
fi

if (( ${#hid_devices[@]} == 0 )); then
    warn "no /dev/hidraw* nodes are visible. USB fans, AIOs, and GPU lighting may stay undiscovered."
else
    log "visible HID nodes: ${hid_devices[*]}"
fi

log "visible USB buses: ${#usb_buses[@]}"

mkdir -p "${OPENRGB_CONFIG_DIR:-/config}"

exec /usr/local/bin/openrgb \
    --server \
    --server-host 0.0.0.0 \
    --server-port "${OPENRGB_SERVER_PORT:-6742}" \
    --config "${OPENRGB_CONFIG_DIR:-/config}" \
    --noautoconnect \
    --loglevel info \
    -v
