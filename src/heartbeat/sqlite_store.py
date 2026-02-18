from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class HeartbeatState:
    heartbeat: float
    is_tense: bool
    focus_text: str
    tense_until_ts: int = 0


@dataclass(slots=True)
class HeartbeatSQLiteStore:
    db_path: Path

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS heartbeat_state (
                    scope TEXT PRIMARY KEY,
                    heartbeat REAL NOT NULL,
                    is_tense INTEGER NOT NULL,
                    focus_text TEXT NOT NULL,
                    tense_until_ts INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            columns = {
                str(row[1]).lower()
                for row in conn.execute("PRAGMA table_info(heartbeat_state)").fetchall()
            }
            if "tense_until_ts" not in columns:
                conn.execute(
                    "ALTER TABLE heartbeat_state ADD COLUMN tense_until_ts INTEGER NOT NULL DEFAULT 0"
                )
            conn.commit()

    def load(self, scope: str) -> HeartbeatState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT heartbeat, is_tense, focus_text, tense_until_ts FROM heartbeat_state WHERE scope = ?",
                (scope,),
            ).fetchone()
        if row is None:
            return None
        heartbeat, is_tense, focus_text, tense_until_ts = row
        return HeartbeatState(
            heartbeat=float(heartbeat),
            is_tense=bool(is_tense),
            focus_text=str(focus_text or ""),
            tense_until_ts=int(tense_until_ts or 0),
        )

    def save(self, scope: str, state: HeartbeatState) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO heartbeat_state(scope, heartbeat, is_tense, focus_text, tense_until_ts, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET
                    heartbeat = excluded.heartbeat,
                    is_tense = excluded.is_tense,
                    focus_text = excluded.focus_text,
                    tense_until_ts = excluded.tense_until_ts,
                    updated_at = excluded.updated_at
                """,
                (
                    scope,
                    float(state.heartbeat),
                    int(state.is_tense),
                    state.focus_text,
                    int(state.tense_until_ts),
                    now,
                ),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
