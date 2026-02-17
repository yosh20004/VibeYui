from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent.service import AgentService, OfficialMCPClient
from src.context import ContextEngine
from src.llm import LLMService
from src.memory import MemoryPool


@dataclass(slots=True)
class ConfigManager:
    """Load dependency settings and construct default service dependencies."""

    dependency_file: Path = Path("config/dependencies.local.json")
    _raw: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        self._raw = {}
        if not self.dependency_file.exists():
            return

        try:
            parsed = json.loads(self.dependency_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if isinstance(parsed, dict):
            self._raw = parsed

    def section(self, name: str) -> dict[str, Any]:
        value = self._raw.get(name)
        if isinstance(value, dict):
            return value
        return {}

    def build_llm_service(self) -> LLMService:
        llm = self.section("llm")
        return LLMService(
            api_url=self._pick_str(llm, "api_url", env_key="LLM_API_URL"),
            api_key=self._pick_str(llm, "api_key", env_key="LLM_API_KEY"),
            timeout=self._pick_float(llm, "timeout", default=15.0),
            model=self._pick_str(llm, "model", default="default"),
        )

    def build_mcp_client(self) -> OfficialMCPClient | None:
        mcp = self.section("mcp")
        enabled = self._pick_bool(mcp, "enabled", env_key="MCP_ENABLED", default=False)
        if not enabled:
            return None

        command = self._pick_str(mcp, "server_cmd", env_key="MCP_SERVER_CMD")
        if not command:
            return None

        return OfficialMCPClient(
            command=command,
            request_timeout=self._pick_float(
                mcp,
                "request_timeout",
                env_key="MCP_REQUEST_TIMEOUT",
                default=10.0,
            ),
            startup_timeout=self._pick_float(mcp, "startup_timeout", default=15.0),
        )

    def build_agent_service(self, llm_service: LLMService) -> AgentService:
        agent = self.section("agent")
        return AgentService(
            llm_service=llm_service,
            mcp_client=self.build_mcp_client(),
            max_steps=self._pick_int(agent, "max_steps", default=3),
        )

    def build_memory_pool(self) -> MemoryPool:
        memory = self.section("memory")
        path = self._pick_str(memory, "file_path", default="data/memory_pool.jsonl")
        return MemoryPool(file_path=Path(path))

    def build_context_engine(self, memory_pool: MemoryPool) -> ContextEngine:
        context = self.section("context")
        return ContextEngine(
            memory_pool=memory_pool,
            recent_limit=self._pick_int(context, "recent_limit", default=100),
        )

    def _pick_str(
        self,
        section: dict[str, Any],
        key: str,
        *,
        env_key: str | None = None,
        default: str | None = None,
    ) -> str | None:
        value = section.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value:
                return value

        if env_key:
            env_value = os.getenv(env_key)
            if env_value is not None:
                env_value = env_value.strip()
                if env_value:
                    return env_value

        return default

    def _pick_float(
        self,
        section: dict[str, Any],
        key: str,
        *,
        env_key: str | None = None,
        default: float,
    ) -> float:
        value: Any = section.get(key)
        if value is None and env_key:
            value = os.getenv(env_key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _pick_int(self, section: dict[str, Any], key: str, *, default: int) -> int:
        value = section.get(key)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default

    def _pick_bool(
        self,
        section: dict[str, Any],
        key: str,
        *,
        env_key: str | None = None,
        default: bool,
    ) -> bool:
        value: Any = section.get(key)
        if value is None and env_key:
            value = os.getenv(env_key)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default
