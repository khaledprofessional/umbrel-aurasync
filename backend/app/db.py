"""SQLite persistence for settings, groups, mappings, presets, and webhook logs."""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import AppSettings, Group, Mapping, MappingInput, WebhookPreset

LOGGER = logging.getLogger(__name__)

SCHEMA_VERSION = 1

DEFAULT_PRESETS: tuple[WebhookPreset, ...] = (
    WebhookPreset(event="download_complete", color="#3b82f6", effect="flash", duration=6, brightness=100),
    WebhookPreset(event="server_alert", color="#ef4444", effect="pulse", duration=10, brightness=100),
    WebhookPreset(event="ci_failed", color="#ef4444", effect="flash", duration=8, brightness=100),
    WebhookPreset(event="success", color="#22c55e", effect="pulse", duration=4, brightness=100),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """A tiny, synchronous SQLite store. Every public method is lock-protected."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), timeout=15, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    zones TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mappings (
                    id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    params TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(target_type, target_id)
                );

                CREATE TABLE IF NOT EXISTS webhook_presets (
                    event TEXT PRIMARY KEY,
                    color TEXT NOT NULL,
                    effect TEXT NOT NULL,
                    duration REAL NOT NULL,
                    brightness INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS webhook_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    source_ip TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_webhook_log_created
                    ON webhook_log(created_at DESC);
                """
            )
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version < SCHEMA_VERSION:
                self._conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            count = self._conn.execute("SELECT COUNT(*) FROM webhook_presets").fetchone()[0]
            if count == 0:
                for preset in DEFAULT_PRESETS:
                    self._conn.execute(
                        """
                        INSERT INTO webhook_presets(event, color, effect, duration, brightness, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            preset.event,
                            preset.color,
                            preset.effect,
                            preset.duration,
                            preset.brightness,
                            utc_now(),
                        ),
                    )
            if self.get_setting_raw("app_settings") is None:
                self.set_setting_raw("app_settings", AppSettings().model_dump())
        self._prune_logs()

    # ------------------------------------------------------------------ settings
    def get_setting_raw(self, key: str) -> Any | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else None

    def set_setting_raw(self, key: str, value: Any) -> None:
        encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, encoded),
            )

    def get_settings(self) -> AppSettings:
        value = self.get_setting_raw("app_settings") or {}
        return AppSettings.model_validate(value)

    def save_settings(self, settings: AppSettings) -> AppSettings:
        self.set_setting_raw("app_settings", settings.model_dump())
        return settings

    def get_or_create_webhook_token(self, generator: Callable[[], str] | None = None) -> str:
        token = self.get_setting_raw("webhook_token")
        if token:
            return str(token)
        token = (generator or (lambda: secrets.token_urlsafe(32)))()
        self.set_setting_raw("webhook_token", token)
        return token

    # -------------------------------------------------------------------- groups
    @staticmethod
    def _group_from_row(row: sqlite3.Row) -> Group:
        return Group(
            id=row["id"],
            name=row["name"],
            zones=json.loads(row["zones"]),
            created_at=row["created_at"],
        )

    def list_groups(self) -> list[Group]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM groups ORDER BY created_at ASC").fetchall()
        return [self._group_from_row(row) for row in rows]

    def create_group(self, name: str, zones: list[str]) -> Group:
        group = Group(id=uuid4().hex[:12], name=name, zones=zones, created_at=utc_now())
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO groups(id, name, zones, created_at) VALUES (?, ?, ?, ?)",
                (group.id, group.name, json.dumps(group.zones), group.created_at),
            )
        return group

    def update_group(self, group_id: str, name: str, zones: list[str]) -> Group | None:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE groups SET name = ?, zones = ? WHERE id = ?",
                (name, json.dumps(zones), group_id),
            )
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
        return self._group_from_row(row)

    def delete_group(self, group_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
            if cursor.rowcount == 0:
                return False
            self._conn.execute(
                "DELETE FROM mappings WHERE target_type = 'group' AND target_id = ?",
                (group_id,),
            )
        return True

    # ------------------------------------------------------------------ mappings
    @staticmethod
    def _mapping_from_row(row: sqlite3.Row) -> Mapping:
        return Mapping(
            id=row["id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            mode=row["mode"],
            params=json.loads(row["params"]),
            enabled=bool(row["enabled"]),
        )

    def list_mappings(self) -> list[Mapping]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM mappings ORDER BY created_at ASC").fetchall()
        return [self._mapping_from_row(row) for row in rows]

    def get_mapping(self, mapping_id: str) -> Mapping | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM mappings WHERE id = ?", (mapping_id,)).fetchone()
        return self._mapping_from_row(row) if row else None

    def find_mapping(self, target_type: str, target_id: str) -> Mapping | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM mappings WHERE target_type = ? AND target_id = ?",
                (target_type, target_id),
            ).fetchone()
        return self._mapping_from_row(row) if row else None

    def create_mapping(self, payload: MappingInput) -> Mapping:
        mapping = Mapping(id=uuid4().hex[:12], **payload.model_dump())
        now = utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO mappings(id, target_type, target_id, mode, params, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mapping.id,
                    mapping.target_type,
                    mapping.target_id,
                    mapping.mode,
                    json.dumps(mapping.params.model_dump()),
                    int(mapping.enabled),
                    now,
                    now,
                ),
            )
        return mapping

    def update_mapping(self, mapping_id: str, payload: MappingInput) -> Mapping | None:
        now = utc_now()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE mappings
                SET target_type = ?, target_id = ?, mode = ?, params = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.target_type,
                    payload.target_id,
                    payload.mode,
                    json.dumps(payload.params.model_dump()),
                    int(payload.enabled),
                    now,
                    mapping_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute("SELECT * FROM mappings WHERE id = ?", (mapping_id,)).fetchone()
        return self._mapping_from_row(row)

    def delete_mapping(self, mapping_id: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM mappings WHERE id = ?", (mapping_id,))
        return cursor.rowcount > 0

    # ------------------------------------------------------------------- presets
    def list_presets(self) -> list[WebhookPreset]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM webhook_presets ORDER BY event ASC").fetchall()
        return [
            WebhookPreset(
                event=row["event"],
                color=row["color"],
                effect=row["effect"],
                duration=row["duration"],
                brightness=row["brightness"],
            )
            for row in rows
        ]

    def get_preset(self, event: str) -> WebhookPreset | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM webhook_presets WHERE event = ?", (event,)).fetchone()
        if not row:
            return None
        return WebhookPreset(
            event=row["event"],
            color=row["color"],
            effect=row["effect"],
            duration=row["duration"],
            brightness=row["brightness"],
        )

    def save_preset(self, preset: WebhookPreset) -> WebhookPreset:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO webhook_presets(event, color, effect, duration, brightness, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(event) DO UPDATE SET
                    color = excluded.color,
                    effect = excluded.effect,
                    duration = excluded.duration,
                    brightness = excluded.brightness,
                    updated_at = excluded.updated_at
                """,
                (
                    preset.event,
                    preset.color,
                    preset.effect,
                    preset.duration,
                    preset.brightness,
                    utc_now(),
                ),
            )
        return preset

    def delete_preset(self, event: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM webhook_presets WHERE event = ?", (event,))
        return cursor.rowcount > 0

    # ---------------------------------------------------------------------- logs
    def log_webhook(
        self,
        event: str,
        outcome: str,
        source_ip: str,
        detail: dict[str, Any] | str | None = None,
    ) -> None:
        if detail is None:
            detail_text = "{}"
        elif isinstance(detail, str):
            detail_text = json.dumps({"message": detail}, ensure_ascii=False)
        else:
            detail_text = json.dumps(detail, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO webhook_log(event, outcome, source_ip, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (event, outcome, source_ip, detail_text, utc_now()),
            )
        self._prune_logs()

    def _prune_logs(self, keep: int = 500) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                DELETE FROM webhook_log
                WHERE id NOT IN (SELECT id FROM webhook_log ORDER BY id DESC LIMIT ?)
                """,
                (keep,),
            )

    def list_webhook_logs(self, limit: int = 60) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM webhook_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            try:
                detail = json.loads(row["detail"])
            except json.JSONDecodeError:
                detail = {}
            records.append(
                {
                    "id": row["id"],
                    "event": row["event"],
                    "outcome": row["outcome"],
                    "source_ip": row["source_ip"],
                    "detail": detail,
                    "created_at": row["created_at"],
                }
            )
        return records

    def last_webhook(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM webhook_log WHERE outcome = 'applied' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        try:
            detail = json.loads(row["detail"])
        except json.JSONDecodeError:
            detail = {}
        return {
            "id": row["id"],
            "event": row["event"],
            "outcome": row["outcome"],
            "source_ip": row["source_ip"],
            "detail": detail,
            "created_at": row["created_at"],
        }

    def clear_webhook_logs(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM webhook_log")

    def close(self) -> None:
        with self._lock:
            self._conn.close()
