from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from app.config import (
    AppSettings,
    GroupInput,
    MappingInput,
    MappingParams,
    WebhookPreset,
)
from app.db import Database


def test_database_round_trip(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    try:
        assert db.get_settings().brightness == 85
        db.save_settings(AppSettings(brightness=42, fps=9))
        assert db.get_settings().brightness == 42
        assert db.get_settings().fps == 9

        assert len(db.list_presets()) >= 4
        db.save_preset(WebhookPreset(event="backup_done", color="#22c55e", effect="pulse", duration=3))
        assert db.get_preset("backup_done") is not None
        assert db.delete_preset("backup_done")
        assert db.get_preset("backup_done") is None

        group = db.create_group("Pair", ["dev1:z0", "dev1:z1"])
        assert db.list_groups()[0].name == "Pair"

        mapping = db.create_mapping(
            MappingInput(
                target_type="group",
                target_id=group.id,
                mode="storage",
                params=MappingParams(path="/"),
            )
        )
        assert mapping.id
        assert db.find_mapping("group", group.id).mode == "storage"
        assert db.update_group(group.id, "Renamed", ["dev1:z0", "dev1:z1"]).name == "Renamed"

        db.log_webhook("download_complete", "applied", "127.0.0.1", {"color": "#3b82f6"})
        logs = db.list_webhook_logs()
        assert logs[0]["event"] == "download_complete"
        assert logs[0]["detail"]["color"] == "#3b82f6"

        assert db.delete_group(group.id)
        assert db.list_mappings() == []
        assert db.list_groups() == []
    finally:
        db.close()


def test_duplicate_target_is_rejected(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    try:
        payload = MappingInput(
            target_type="zone",
            target_id="dev1:z0",
            mode="static",
            params=MappingParams(),
        )
        db.create_mapping(payload)
        with pytest.raises(sqlite3.IntegrityError):
            db.create_mapping(payload)
    finally:
        db.close()


def test_token_is_stable(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    try:
        token = db.get_or_create_webhook_token()
        assert token
        assert db.get_or_create_webhook_token() == token
    finally:
        db.close()


def test_group_input_rejects_duplicates() -> None:
    with pytest.raises(ValidationError):
        GroupInput(name="bad", zones=["a", "a"])
