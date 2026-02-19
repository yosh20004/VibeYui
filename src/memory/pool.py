from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MemoryPool:
    """Manage long-term memory and persist each write to disk."""

    file_path: Path = Path("data/memory_pool")
    _records_by_scope: dict[str, list[str]] = field(default_factory=dict, init=False, repr=False)
    _base_dir: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._base_dir = self._resolve_base_dir(self.file_path)
        self._base_dir.mkdir(parents=True, exist_ok=True)

        for path in sorted(self._base_dir.glob("*.jsonl")):
            scope = path.stem
            records = self._records_by_scope.setdefault(scope, [])
            self._load_file(path, records)

    def append(
        self,
        value: str,
        *,
        scope: str = "default",
        timestamp: str | None = None,
        user_name: str | None = None,
    ) -> None:
        item = value.strip()
        if not item:
            return

        normalized_scope = self._normalize_scope(scope)
        records = self._records_by_scope.setdefault(normalized_scope, [])
        payload: dict[str, Any] = {
            "value": item,
            "timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        }
        if user_name:
            payload["user_name"] = user_name

        with self._scope_file(normalized_scope).open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
            fp.flush()

        records.append(item)

    def recent(self, limit: int, *, scope: str = "default") -> list[str]:
        if limit <= 0:
            return []
        records = self._records_by_scope.get(self._normalize_scope(scope), [])
        return records[-limit:]

    def older_than_recent(self, recent_limit: int, *, limit: int | None = None, scope: str = "default") -> list[str]:
        if recent_limit < 0:
            recent_limit = 0

        records = self._records_by_scope.get(self._normalize_scope(scope), [])
        end = max(0, len(records) - recent_limit)
        older = records[:end]
        if limit is None or limit <= 0:
            return older
        return older[-limit:]

    def _resolve_base_dir(self, path: Path) -> Path:
        if path.suffix:
            return path.parent / path.stem
        return path

    def _normalize_scope(self, scope: str) -> str:
        clean = scope.strip()
        if not clean:
            return "default"
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in clean)

    def _scope_file(self, scope: str) -> Path:
        return self._base_dir / f"{scope}.jsonl"

    def _load_file(self, path: Path, records: list[str]) -> None:
        with path.open("r", encoding="utf-8") as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                value = payload.get("value")
                if isinstance(value, str):
                    records.append(value)
