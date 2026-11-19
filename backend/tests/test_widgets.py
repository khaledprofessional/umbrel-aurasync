from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.config import MappingInput, MappingParams
from app.db import Database
from app.main import _storage_widget, _webhook_widget
from app.state import AppState


def make_context(tmp_path):
    db = Database(tmp_path / "widget.db")
    state = AppState(db, "widget-token")
    state.set_devices(
        [
            {
                "key": "dev-1",
                "index": 0,
                "name": "RAM",
                "zones": [{"id": "dev-1:z0", "index": 0, "name": "DRAM", "led_count": 8}],
            }
        ]
    )
    state.set_telemetry(
        {
            "cpu": {"load": 12, "temp": 44},
            "memory": {"total": 100, "used": 30, "percent": 30},
            "gpu": None,
            "storage": {
                "/": {
                    "path": "/",
                    "used_percent": 68.0,
                    "free_percent": 32.0,
                    "free_human": "1.0 TB",
                    "total_human": "3.0 TB",
                }
            },
            "sensors": [],
        }
    )
    state.set_hardware({"connected": True, "device_count": 1})
    return SimpleNamespace(state=state, db=db)


def test_widget_status_shape(tmp_path) -> None:
    context = make_context(tmp_path)
    db = context.db
    try:
        db.create_mapping(
            MappingInput(
                target_type="zone",
                target_id="dev-1:z0",
                mode="storage",
                params=MappingParams(),
            )
        )
        db.log_webhook("download_complete", "applied", "127.0.0.1", {"effect": "flash"})
        context.state.reload_config()
        widget = asyncio.run(_webhook_widget(context))
        assert widget["type"] == "list-emoji"
        assert widget["refresh"] == "5s"
        assert widget["count"] == "1"
        assert len(widget["items"]) == 3
        assert "Storage gauge" in widget["items"][0]["text"]
        assert "68% used" in widget["items"][1]["text"]
        assert "download_complete" in widget["items"][2]["text"]
    finally:
        db.close()


def test_storage_widget_shape(tmp_path) -> None:
    context = make_context(tmp_path)
    try:
        widget = asyncio.run(_storage_widget(context))
        assert widget["type"] == "text-with-progress"
        assert widget["progress"] == 0.68
        assert "68%" == widget["text"]
        assert "T" in widget["subtext"]
    finally:
        context.db.close()
