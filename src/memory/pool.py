from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MemoryPool:
    """Manage long-term memory and persist each write to disk."""

    file_path: Path = Path("data/memory_pool.jsonl")
    _records: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self.file_path.touch()
            return

        with self.file_path.open("r", encoding="utf-8") as fp:
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
                    self._records.append(value)

    def append(self, value: str) -> None:
        item = value.strip()
        if not item:
            return

        payload: dict[str, Any] = {"value": item}
        with self.file_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
            fp.flush()

        self._records.append(item)

    def recent(self, limit: int) -> list[str]:
        if limit <= 0:
            return []
        return self._records[-limit:]

    def older_than_recent(self, recent_limit: int, *, limit: int | None = None) -> list[str]:
        if recent_limit < 0:
            recent_limit = 0

        end = max(0, len(self._records) - recent_limit)
        older = self._records[:end]
        if limit is None or limit <= 0:
            return older
        return older[-limit:]
