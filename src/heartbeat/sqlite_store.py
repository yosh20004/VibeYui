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
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def load(self, scope: str) -> HeartbeatState | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT heartbeat, is_tense, focus_text FROM heartbeat_state WHERE scope = ?",
                (scope,),
            ).fetchone()
        if row is None:
            return None
        heartbeat, is_tense, focus_text = row
        return HeartbeatState(
            heartbeat=float(heartbeat),
            is_tense=bool(is_tense),
            focus_text=str(focus_text or ""),
        )

    def save(self, scope: str, state: HeartbeatState) -> None:
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO heartbeat_state(scope, heartbeat, is_tense, focus_text, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET
                    heartbeat = excluded.heartbeat,
                    is_tense = excluded.is_tense,
                    focus_text = excluded.focus_text,
                    updated_at = excluded.updated_at
                """,
                (
                    scope,
                    float(state.heartbeat),
                    int(state.is_tense),
                    state.focus_text,
                    now,
                ),
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
