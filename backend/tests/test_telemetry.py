from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppSettings
from app.telemetry import TelemetryService


def make_service(tmp_path: Path) -> TelemetryService:
    runtime = type(
        "Runtime",
        (),
        {
            "host_root": tmp_path,
            "host_proc": tmp_path / "proc",
            "host_sys": tmp_path / "sys",
            "host_os_release": tmp_path / "os-release",
        },
    )()
    return TelemetryService(runtime, AppSettings, lambda: {"/"})  # type: ignore[arg-type]


def test_storage_usage_maps_host_root(tmp_path) -> None:
    service = make_service(tmp_path)
    usage = service.storage_usage("/")
    assert usage["path"] == "/"
    assert usage["total"] > 0
    assert 0 <= usage["used_percent"] <= 100
    assert usage["free_human"]


def test_host_path_rejects_relative_and_escape(tmp_path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(ValueError):
        service.host_path("mnt/data")
    # Absolute paths are normalised inside the host root, never against the
    # container's own root file system.
    normalized = service.host_path("/mnt/../../etc")
    assert normalized == (tmp_path / "etc").resolve()
    resolved = service.host_path("/mnt/data")
    assert str(resolved).startswith(str(tmp_path))


def test_unknown_storage_path_reports_error(tmp_path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(ValueError):
        service.storage_usage("/definitely-not-a-real-mount")


def test_sensor_picker_prefers_package() -> None:
    sensors = [
        {"id": "a", "label": "coretemp · Core 0", "temp": 70, "kind": "cpu", "chip": "coretemp"},
        {"id": "b", "label": "coretemp · Package id 0", "temp": 65, "kind": "cpu", "chip": "coretemp"},
    ]
    picked = TelemetryService._pick_sensor(sensors, "auto", "cpu")
    assert picked is not None
    assert picked["id"] == "b"


def test_sensor_picker_named() -> None:
    sensors = [{"id": "x", "label": "x", "temp": 40, "kind": "gpu", "chip": "amdgpu"}]
    assert TelemetryService._pick_sensor(sensors, "x", "gpu")["id"] == "x"
