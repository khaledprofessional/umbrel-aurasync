# Host setup for RGB hardware

AuraSync runs OpenRGB inside a privileged container, but the Linux kernel interfaces it needs belong to the **host**. This page covers the one-time setup, how to verify it, and what to do when hardware stays invisible.

## What OpenRGB needs

| Hardware path | Kernel interface | Typical devices |
| --- | --- | --- |
| DDR4/DDR5 RGB RAM | SMBus over `/dev/i2c-*` | Corsair Vengeance, G.Skill Trident, Kingston Fury |
| Motherboard ARGB headers | SMBus / Super I/O | ASUS Aura, MSI Mystic Light, Gigabyte RGB Fusion |
| USB fan controllers, AIOs, GPU logos | `/dev/hidraw*`, `/dev/bus/usb` | Corsair Commander, NZXT, Razer, EVGA, some GPUs |
| GPU RGB | USB HID or SMBus | ASUS/MSI/Gigabyte/EVGA GPUs |

The controller container is privileged because bus and HID paths are unique to every machine. The backend that parses webhooks is **not** privileged.

## One-time setup

Connect to the umbrelOS host over SSH:

```bash
ssh umbrel@umbrel.local
```

### 1. Load the I2C device interface

```bash
sudo modprobe i2c-dev
```

This creates `/dev/i2c-*`. Without it, OpenRGB can often still see USB devices but not RAM or SMBus motherboard controllers.

### 2. Load the chipset SMBus driver

Most x86 systems need one of these:

```bash
# Intel PCH (most umbrel Home / NUC / common servers)
sudo modprobe i2c-i801

# AMD FCH / PCH
sudo modprobe i2c-piix4

# Some Nuvoton Super I/O motherboards
sudo modprobe i2c-nct6793
```

Only the driver matching your chipset will load. Errors for the others are harmless. To see what your chipset is:

```bash
lspci -nn | grep -Ei 'ISA|SMBus|I2C'
```

### 3. Persist across reboots

```bash
echo i2c-dev | sudo tee /etc/modules-load.d/aurasync.conf
echo i2c-i801 | sudo tee -a /etc/modules-load.d/aurasync.conf
# Replace i2c-i801 with i2c-piix4 on AMD.
```

Some umbrelOS updates may replace `/etc`; re-check the file after a major OS upgrade. The app’s **Settings → SMBus diagnostics** always shows the live state.

### 4. Verify

```bash
sudo apt-get update && sudo apt-get install -y i2c-tools
i2cdetect -l
ls -l /dev/i2c-*
ls -l /dev/hidraw*
lsusb
```

A healthy Intel system looks similar to:

```text
i2c-0   i2c   SMBus I801 adapter at f040   I2C adapter
crw-rw---- 1 root i2c 89, 0 ... /dev/i2c-0
```

You do **not** need to add your user to the `i2c` group for the app; the OpenRGB container is privileged.

### 5. Restart AuraSync

In umbrelOS, open the app → **…** → **Restart**, or use the dashboard’s **Devices → Rescan**. OpenRGB’s entrypoint also attempts `modprobe` on every start, so a reboot of the app is often enough after module installation.

## USB-only hardware

Fan controllers, AIOs, and many GPU logos need no host module setup. The privileged container gets `/dev/hidraw*` and `/dev/bus/usb` automatically. If they remain invisible:

- confirm the device is connected and powered;
- check `lsusb` on the host;
- check the OpenRGB supported-devices list;
- inspect the OpenRGB container log for HID visibility warnings;
- ensure no other vendor RGB service on the host is holding the device.

## Reading the diagnostics

**Settings → SMBus diagnostics** shows:

| Field | Meaning |
| --- | --- |
| i2c-dev module | Whether `i2c_dev` appears in `/proc/modules` (or a built-in interface exists) |
| SMBus driver | Whether `i2c-i801`, `i2c-piix4`, or `i2c-nct6793` is loaded |
| I2C adapters | Count of `/sys/bus/i2c/devices/i2c-*` entries |
| hidraw nodes | Count of `/sys/class/hidraw/hidraw*` entries |
| Recommendations | Concrete commands based on the observed state |

The app deliberately treats “module not loaded” as a warning rather than a hard failure: some kernels build the driver in, and USB-only setups do not need SMBus at all.

## Common problems

### RAM sticks are missing

1. `sudo modprobe i2c-dev`
2. `sudo modprobe i2c-i801` or `i2c-piix4`
3. Restart the app, then **Rescan**.
4. Confirm the sticks are in OpenRGB’s supported list; RGB control differs by model and firmware.
5. Some boards require enabling “SPD write” or disabling a BIOS “DRAM RGB” lock. Consult the OpenRGB wiki for your board.

### Motherboard headers are missing

- The controller may be a Super I/O device rather than SMBus; try `i2c-nct6793`.
- ASUS boards sometimes need the `acpi_enforce_resources=lax` kernel parameter. This is a host bootloader change and is outside AuraSync’s control.
- Only the ARGB header controller appears; individual strips are not separate devices.

### GPU is missing

- Many GPUs expose lighting over USB HID, not SMBus.
- Check `lsusb` and whether OpenRGB supports the exact model.
- Laptop GPUs and some OEM cards have no addressable lighting controller.

### OpenRGB container exits repeatedly

Check logs from umbrelOS Docker or:

```bash
sudo docker ps --filter name=aura-sync_openrgb
sudo docker logs --tail 100 aura-sync_openrgb_1
```

The entrypoint logs every module attempt and the visible `/dev` nodes. A failed `modprobe` is a warning, not an exit; an OpenRGB crash is a real failure.

### OpenRGB logs “udev rules are not installed”

This warning is expected inside the container: the image does not run udev, and OpenRGB runs as root with privileged device access instead. It is informational unless a specific USB device still fails to appear.

### `i2cdetect` shows nothing

- The SMBus driver may not match the chipset.
- Some kernels hide SMBus behind `i2c-i801` even on AMD-branded systems; check `lspci`.
- Virtual machines generally do not expose the host SMBus. AuraSync must run on the physical umbrelOS host, not inside a VM without PCI passthrough.

### Webhooks work but lights do not change

- Confirm a mapping exists for the target zone.
- Check **Mappings → Test**; this bypasses the webhook path.
- Confirm the OpenRGB connection pill is green.
- Some devices need to be switched to Direct mode; AuraSync does this once per connection automatically.
- If a webhook targets `managed` and no mapping exists, AuraSync falls back to all zones for that overlay.

### Storage path rejected

Paths are resolved inside the host root, read-only. Use a path that exists on the host, such as `/`, `/mnt/data`, or a mounted external drive. The dashboard suggests visible mounts; typed paths are checked with `statvfs` before saving.

## Uninstall / rollback

Removing the app removes its containers and app data. The host modules remain loaded until reboot; remove `/etc/modules-load.d/aurasync.conf` if you want to stop loading them automatically:

```bash
sudo rm /etc/modules-load.d/aurasync.conf
```

Modules already loaded can be unloaded only if nothing is using them; usually a reboot is simpler.
