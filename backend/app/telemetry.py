"""Host telemetry collection.

The container is intentionally not privileged. It reads read-only bind mounts of
the host's /proc, /sys and / so CPU load, sensors, and file-system usage reflect
the real machine rather than the container.
"""

from __future__ import annotations

import asyncio
import copy
import logging
import os
import posixpath
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AppSettings, RuntimeConfig

LOGGER = logging.getLogger(__name__)

PSEUDO_FILESYSTEMS = {
    "proc",
    "sysfs",
    "tmpfs",
    "devtmpfs",
    "devpts",
    "cgroup",
    "cgroup2",
    "securityfs",
    "pstore",
    "efivarfs",
    "bpf",
    "tracefs",
    "debugfs",
    "hugetlbfs",
    "mqueue",
    "configfs",
    "fusectl",
    "autofs",
    "binfmt_misc",
    "rpc_pipefs",
    "nsfs",
    "squashfs",
    "ramfs",
}

CPU_CHIPS = {"coretemp", "k10temp", "zenpower", "cpu_thermal", "cpu-thermal", "acpitz"}
GPU_CHIPS = {"amdgpu", "radeon", "nouveau", "nvidia", "i915", "xe"}

MOUNT_UNESCAPE_RE = re.compile(r"\\([0-7]{3})")


@dataclass(slots=True)
class CpuTimes:
    total: int
    idle: int


@dataclass(slots=True)
class TelemetrySnapshot:
    timestamp: float = 0.0
    cpu_load: float = 0.0
    cpu_temp: float | None = None
    cpu_sensor_id: str | None = None
    cpu_sensor_label: str | None = None
    memory_total: int = 0
    memory_used: int = 0
    memory_percent: float = 0.0
    gpu: dict[str, Any] | None = None
    storage: dict[str, dict[str, Any]] = field(default_factory=dict)
    sensors: list[dict[str, Any]] = field(default_factory=list)
    uptime: float = 0.0
    loadavg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    hostname: str = ""
    os_name: str = ""
    cpu_model: str = ""
    cpu_cores: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cpu": {
                "load": round(self.cpu_load, 1),
                "temp": self.cpu_temp,
                "sensor_id": self.cpu_sensor_id,
                "sensor_label": self.cpu_sensor_label,
                "model": self.cpu_model,
                "cores": self.cpu_cores,
            },
            "memory": {
                "total": self.memory_total,
                "used": self.memory_used,
                "percent": round(self.memory_percent, 1),
            },
            "gpu": self.gpu,
            "storage": self.storage,
            "sensors": self.sensors,
            "uptime": self.uptime,
            "loadavg": list(self.loadavg),
            "hostname": self.hostname,
            "os_name": self.os_name,
            "errors": self.errors,
        }


def _read(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return default


def _to_int(value: str) -> int | None:
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


def _unescape_mount(value: str) -> str:
    return MOUNT_UNESCAPE_RE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _human_bytes(value: int) -> str:
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    number = float(value)
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:.1f} {unit}" if unit != "B" else f"{int(number)} B"
        number /= 1024
    return f"{value} B"


class TelemetryService:
    def __init__(
        self,
        runtime: RuntimeConfig,
        settings_getter: Callable[[], AppSettings],
        storage_paths_getter: Callable[[], set[str]],
        interval: float = 2.0,
    ) -> None:
        self.runtime = runtime
        self.settings_getter = settings_getter
        self.storage_paths_getter = storage_paths_getter
        self.interval = interval
        self._previous_cpu: CpuTimes | None = None
        self._sensor_cache: list[dict[str, Any]] = []
        self._sensor_cache_at = 0.0
        self._latest = TelemetrySnapshot()
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._last_error: str | None = None

    @property
    def latest(self) -> TelemetrySnapshot:
        return self._latest

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._latest.to_dict())

    def request_refresh(self) -> None:
        self._wake.set()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                snapshot = await asyncio.to_thread(self.collect)
                async with self._lock:
                    self._latest = snapshot
                self._last_error = None
            except Exception as exc:  # pragma: no cover - defensive loop guard
                self._last_error = str(exc)
                LOGGER.exception("Telemetry collection failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.interval)
                await asyncio.sleep(0.05)
            except TimeoutError:
                pass

    # ------------------------------------------------------------------- public
    def collect(self) -> TelemetrySnapshot:
        settings = self.settings_getter()
        errors: list[str] = []
        cpu_load = self._cpu_load()
        memory = self._memory()
        sensors = self._read_sensors()
        self._sensor_cache = sensors
        self._sensor_cache_at = time.time()

        cpu_sensor = self._pick_sensor(sensors, settings.cpu_sensor, "cpu")
        gpu = self._read_gpu(settings.gpu_sensor, sensors)
        gpu_sensor = self._pick_sensor(sensors, settings.gpu_sensor, "gpu")
        if gpu and gpu.get("temp") is None and gpu_sensor:
            gpu["temp"] = gpu_sensor["temp"]
            gpu["sensor_id"] = gpu_sensor["id"]
            gpu["sensor_label"] = gpu_sensor["label"]

        paths = set(self.storage_paths_getter())
        paths.add(settings.storage_path or "/")
        storage: dict[str, dict[str, Any]] = {}
        for path in sorted(paths):
            try:
                storage[path] = self.storage_usage(path)
            except ValueError as exc:
                errors.append(f"{path}: {exc}")

        info = self._host_info()
        return TelemetrySnapshot(
            timestamp=time.time(),
            cpu_load=cpu_load,
            cpu_temp=cpu_sensor["temp"] if cpu_sensor else None,
            cpu_sensor_id=cpu_sensor["id"] if cpu_sensor else None,
            cpu_sensor_label=cpu_sensor["label"] if cpu_sensor else None,
            memory_total=memory["total"],
            memory_used=memory["used"],
            memory_percent=memory["percent"],
            gpu=gpu,
            storage=storage,
            sensors=sensors,
            uptime=info["uptime"],
            loadavg=info["loadavg"],
            hostname=info["hostname"],
            os_name=info["os_name"],
            cpu_model=info["cpu_model"],
            cpu_cores=info["cpu_cores"],
            errors=errors,
        )

    def sensors(self) -> list[dict[str, Any]]:
        if time.time() - self._sensor_cache_at > 15 or not self._sensor_cache:
            self._sensor_cache = self._read_sensors()
            self._sensor_cache_at = time.time()
        return copy.deepcopy(self._sensor_cache)

    # ------------------------------------------------------------------- CPU/RAM
    def _read_cpu_times(self) -> CpuTimes | None:
        text = _read(self.runtime.host_proc / "stat")
        first = text.splitlines()[0] if text else ""
        if not first.startswith("cpu "):
            return None
        values = [int(part) for part in first.split()[1:] if part.isdigit()]
        if len(values) < 4:
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)
        return CpuTimes(total=total, idle=idle)

    def _cpu_load(self) -> float:
        current = self._read_cpu_times()
        if current is None:
            return 0.0
        previous = self._previous_cpu
        self._previous_cpu = current
        if previous is None:
            return 0.0
        total_delta = current.total - previous.total
        idle_delta = current.idle - previous.idle
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))

    def _memory(self) -> dict[str, Any]:
        text = _read(self.runtime.host_proc / "meminfo")
        values: dict[str, int] = {}
        for line in text.splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            number = raw.strip().split()[0] if raw.strip() else "0"
            try:
                values[key] = int(number) * 1024
            except ValueError:
                continue
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", values.get("MemFree", 0))
        used = max(0, total - available)
        percent = (used / total * 100.0) if total else 0.0
        return {"total": total, "used": used, "percent": percent}

    def _host_info(self) -> dict[str, Any]:
        uptime_text = _read(self.runtime.host_proc / "uptime").split()
        uptime = float(uptime_text[0]) if uptime_text else 0.0
        loadavg_text = _read(self.runtime.host_proc / "loadavg").split()
        loadavg = tuple(float(x) for x in loadavg_text[:3]) if len(loadavg_text) >= 3 else (0.0, 0.0, 0.0)
        hostname = _read(self.runtime.host_proc / "sys/kernel/hostname").strip()
        os_name = ""
        release = _read(self.runtime.host_os_release)
        if not release:
            release = _read(self.runtime.host_root / "etc/os-release")
        for line in release.splitlines():
            if line.startswith("PRETTY_NAME="):
                os_name = line.split("=", 1)[1].strip().strip('"')
                break
        cpuinfo = _read(self.runtime.host_proc / "cpuinfo")
        cpu_model = ""
        cores = 0
        for line in cpuinfo.splitlines():
            if line.startswith("processor"):
                cores += 1
            elif line.lower().startswith("model name") and not cpu_model:
                cpu_model = line.split(":", 1)[1].strip()
        return {
            "uptime": uptime,
            "loadavg": loadavg,
            "hostname": hostname,
            "os_name": os_name,
            "cpu_model": cpu_model,
            "cpu_cores": cores,
        }

    # -------------------------------------------------------------------- sensors
    def _read_sensors(self) -> list[dict[str, Any]]:
        sensors: list[dict[str, Any]] = []
        hwmon_root = self.runtime.host_sys / "class/hwmon"
        try:
            hwmon_dirs = sorted(hwmon_root.glob("hwmon*"))
        except OSError:
            hwmon_dirs = []
        for directory in hwmon_dirs:
            chip = _read(directory / "name").strip() or directory.name
            for temp_input in sorted(directory.glob("temp*_input")):
                suffix = temp_input.stem.removeprefix("temp")
                raw = _to_int(_read(temp_input))
                if raw is None:
                    continue
                temp = raw / 1000.0
                if temp < -50 or temp > 200:
                    continue
                label = _read(directory / f"temp{suffix}_label").strip()
                kind = "cpu" if chip in CPU_CHIPS else "gpu" if chip in GPU_CHIPS else "other"
                sensor_id = f"hwmon:{chip}:temp{suffix}"
                sensors.append(
                    {
                        "id": sensor_id,
                        "chip": chip,
                        "label": f"{chip} · {label}" if label else f"{chip} · temp{suffix}",
                        "temp": round(temp, 1),
                        "kind": kind,
                    }
                )
        thermal_root = self.runtime.host_sys / "class/thermal"
        try:
            thermal_zones = sorted(thermal_root.glob("thermal_zone*"))
        except OSError:
            thermal_zones = []
        for directory in thermal_zones:
            raw = _to_int(_read(directory / "temp"))
            if raw is None:
                continue
            temp = raw / 1000.0
            if temp < -50 or temp > 200:
                continue
            zone_type = _read(directory / "type").strip() or directory.name
            kind = "cpu" if "cpu" in zone_type.lower() or "pkg" in zone_type.lower() else "other"
            sensors.append(
                {
                    "id": f"thermal:{zone_type}:{directory.name}",
                    "chip": "thermal",
                    "label": zone_type,
                    "temp": round(temp, 1),
                    "kind": kind,
                }
            )
        nvidia = self._nvidia()
        if nvidia:
            sensors.append(
                {
                    "id": "nvidia:0",
                    "chip": "nvidia",
                    "label": f"nvidia · {nvidia.get('name', 'GPU 0')}",
                    "temp": nvidia.get("temp") if nvidia.get("temp") is not None else 0.0,
                    "kind": "gpu",
                }
            )
        return sensors

    @staticmethod
    def _pick_sensor(
        sensors: list[dict[str, Any]], wanted: str, kind: str
    ) -> dict[str, Any] | None:
        if wanted and wanted != "auto":
            for sensor in sensors:
                if sensor["id"] == wanted:
                    return sensor
        candidates = [sensor for sensor in sensors if sensor["kind"] == kind]
        if not candidates:
            return None
        if kind == "cpu":
            priorities = ("package", "tctl", "tdie", "cpu", "core")
            for token in priorities:
                for sensor in candidates:
                    if token in sensor["label"].lower():
                        return sensor
            return max(candidates, key=lambda item: item["temp"])
        # GPU: prefer a real GPU chip over thermal fallbacks, then edge/junction.
        for token in ("amdgpu", "nvidia", "nouveau", "radeon"):
            for sensor in candidates:
                if token in sensor["chip"].lower():
                    return sensor
        return max(candidates, key=lambda item: item["temp"])

    def _nvidia(self) -> dict[str, Any] | None:
        binary = shutil.which("nvidia-smi")
        if not binary:
            return None
        try:
            completed = subprocess.run(
                [
                    binary,
                    "--query-gpu=index,name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if not lines:
            return None
        first = [part.strip() for part in lines[0].split(",")]
        if len(first) >= 6:
            try:
                temp = float(first[2]) if first[2] not in ("", "[N/A]") else None
                util = float(first[3]) if first[3] not in ("", "[N/A]") else None
                used = int(first[4]) * 1024 * 1024 if first[4] not in ("", "[N/A]") else None
                total = int(first[5]) * 1024 * 1024 if first[5] not in ("", "[N/A]") else None
            except ValueError:
                return None
            return {
                "index": int(first[0]) if first[0].isdigit() else 0,
                "name": first[1],
                "temp": temp,
                "util": util,
                "memory_used": used,
                "memory_total": total,
                "vendor": "nvidia",
                "sensor_id": "nvidia:0",
                "sensor_label": f"nvidia · {first[1]}",
            }
        return None

    def _read_gpu(self, wanted: str, sensors: list[dict[str, Any]]) -> dict[str, Any] | None:
        nvidia = self._nvidia()
        if (wanted == "auto" or wanted.startswith("nvidia")) and nvidia:
            return nvidia
        if wanted.startswith("hwmon:") or wanted == "auto":
            selected = self._pick_sensor(sensors, wanted, "gpu")
            if selected and selected["chip"] == "nvidia":
                return nvidia
            if selected:
                name = "AMD GPU" if selected["chip"] in {"amdgpu", "radeon"} else selected["label"]
                if wanted.startswith("hwmon:") or not nvidia:
                    return {
                        "index": 0,
                        "name": name,
                        "temp": selected["temp"],
                        "util": None,
                        "memory_used": None,
                        "memory_total": None,
                        "vendor": selected["chip"],
                        "sensor_id": selected["id"],
                        "sensor_label": selected["label"],
                    }
        return nvidia

    # -------------------------------------------------------------------- storage
    def storage_usage(self, path: str) -> dict[str, Any]:
        host_path = self.host_path(path)
        try:
            if hasattr(os, "statvfs"):
                stats = os.statvfs(host_path)
                block = stats.f_frsize or stats.f_bsize
                total = stats.f_blocks * block
                free = stats.f_bavail * block
                used = max(0, (stats.f_blocks - stats.f_bfree) * block)
            else:
                # Development fallback for non-POSIX hosts. Production always
                # uses statvfs so reserved blocks and byte counts match `df`.
                usage = shutil.disk_usage(host_path)
                total, used, free = usage.total, usage.used, usage.free
        except OSError as exc:
            raise ValueError(f"cannot read storage path: {exc.strerror or exc}") from exc
        usable = used + free
        percent = (used / usable * 100.0) if usable else 0.0
        return {
            "path": path,
            "total": total,
            "used": used,
            "free": free,
            "usable": usable,
            "used_percent": round(max(0.0, min(100.0, percent)), 2),
            "free_percent": round(max(0.0, min(100.0, 100.0 - percent)), 2),
            "total_human": _human_bytes(total),
            "free_human": _human_bytes(free),
        }

    def host_path(self, path: str) -> Path:
        if not path or not path.startswith("/") or "\x00" in path:
            raise ValueError("storage path must be absolute")
        normal = posixpath.normpath(path)
        if normal.startswith(".."):
            raise ValueError("storage path escapes the host root")
        root = self.runtime.host_root.resolve()
        candidate = (root / normal.lstrip("/")).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("storage path escapes the host root")
        return candidate

    def mounts(self) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for candidate in ("/", "/mnt", "/mnt/data", "/home", "/data"):
            if candidate == "/" or self.host_path(candidate).exists():
                try:
                    usage = self.storage_usage(candidate)
                    found[candidate] = {
                        "path": candidate,
                        "total": usage["total"],
                        "free": usage["free"],
                        "label": "System root" if candidate == "/" else candidate,
                    }
                except ValueError:
                    pass
        mounts_text = _read(self.runtime.host_proc / "mounts")
        for line in mounts_text.splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            mount_path = _unescape_mount(parts[1])
            fstype = parts[2]
            if fstype in PSEUDO_FILESYSTEMS or not mount_path.startswith("/"):
                continue
            if mount_path in found or len(found) >= 40:
                continue
            try:
                usage = self.storage_usage(mount_path)
            except ValueError:
                continue
            found[mount_path] = {
                "path": mount_path,
                "total": usage["total"],
                "free": usage["free"],
                "label": mount_path,
            }
        return sorted(found.values(), key=lambda item: (item["path"] != "/", item["path"]))

    def diagnostics(self) -> dict[str, Any]:
        modules_text = _read(self.runtime.host_proc / "modules")
        loaded_modules = {
            line.split()[0].replace("-", "_")
            for line in modules_text.splitlines()
            if line.strip()
        }
        module_checks = []
        for name in ("i2c_dev", "i2c_i801", "i2c_piix4", "i2c_nct6793"):
            module_checks.append({"name": name.replace("_", "-"), "loaded": name in loaded_modules})

        i2c_adapters: list[str] = []
        try:
            i2c_adapters = sorted(path.name for path in (self.runtime.host_sys / "bus/i2c/devices").glob("i2c-*"))
        except OSError:
            pass
        hid_devices: list[str] = []
        try:
            hid_devices = sorted(path.name for path in (self.runtime.host_sys / "class/hidraw").glob("hidraw*"))
        except OSError:
            pass
        usb_devices: list[str] = []
        try:
            usb_devices = sorted(path.name for path in (self.runtime.host_sys / "bus/usb/devices").glob("*"))
        except OSError:
            pass

        i2c_loaded = any(item["loaded"] for item in module_checks if item["name"] == "i2c-dev")
        i2c_loaded = i2c_loaded or bool(i2c_adapters)
        smbus_loaded = any(
            item["loaded"] for item in module_checks if item["name"] in {"i2c-i801", "i2c-piix4"}
        )
        smbus_loaded = smbus_loaded or bool(i2c_adapters)
        recommendations: list[str] = []
        if not i2c_loaded and not i2c_adapters:
            recommendations.append(
                "Load the I2C device interface on the umbrelOS host: sudo modprobe i2c-dev"
            )
        if not smbus_loaded and not i2c_adapters:
            recommendations.append(
                "Load your SMBus controller driver: sudo modprobe i2c-i801 (Intel) or sudo modprobe i2c-piix4 (AMD)."
            )
        if not i2c_adapters:
            recommendations.append(
                "No I2C adapters were visible in /sys/bus/i2c/devices. RAM stick lighting will stay undiscovered until the host exposes its SMBus."
            )
        if not hid_devices:
            recommendations.append(
                "No hidraw devices were visible. USB fan, AIO, and GPU controllers need USB HID access through the privileged controller container."
            )

        return {
            "modules": module_checks,
            "i2c_dev_loaded": i2c_loaded,
            "smbus_loaded": smbus_loaded,
            "i2c_adapters": i2c_adapters,
            "hidraw": hid_devices,
            "usb_device_count": len(usb_devices),
            "recommendations": recommendations,
            "host": self._host_info(),
            "os_release": _read(self.runtime.host_os_release).strip(),
        }
