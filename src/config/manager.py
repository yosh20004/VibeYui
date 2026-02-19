from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent.service import AgentService, OfficialMCPClient
from src.core import MessageWorkflow
from src.context import ContextEngine
from src.heartbeat import HeartbeatMonitor, HeartbeatSQLiteStore
from src.llm import LLMService
from src.memory import MemoryPool
from src.router import Router


@dataclass(slots=True)
class ConfigManager:
    """Load dependency settings and construct default service dependencies."""

    dependency_file: Path = Path("data/dependencies.local.json")
    legacy_dependency_file: Path = Path("config/dependencies.local.json")
    _raw: dict[str, Any] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        self._raw = {}
        target = self.dependency_file
        if not target.exists() and self.legacy_dependency_file.exists():
            target = self.legacy_dependency_file

        if not target.exists():
            return

        try:
            parsed = json.loads(target.read_text(encoding="utf-8"))
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
            temperature=self._pick_float_in_range(
                llm,
                "temperature",
                env_key="LLM_TEMPERATURE",
                default=2.0,
                min_value=0.0,
                max_value=2.0,
            ),
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
        heartbeat = self.section("heartbeat")
        heartbeat_store = HeartbeatSQLiteStore(
            db_path=Path(self._pick_str(heartbeat, "sqlite_path", default="data/heartbeat.db") or "data/heartbeat.db")
        )
        heartbeat_monitor = HeartbeatMonitor(
            state_store=heartbeat_store,
            state_scope=self._pick_str(heartbeat, "scope", default="default") or "default",
            tense_hold_seconds=self._pick_int(heartbeat, "tense_hold_seconds", default=15 * 60),
        )
        return ContextEngine(
            memory_pool=memory_pool,
            heartbeat_monitor=heartbeat_monitor,
            recent_limit=self._pick_int(context, "recent_limit", default=100),
        )

    def build_router(
        self,
        *,
        llm_service: LLMService | None = None,
        agent_service: AgentService | None = None,
        memory_pool: MemoryPool | None = None,
        context_engine: ContextEngine | None = None,
    ) -> Router:
        resolved_llm = llm_service or self.build_llm_service()
        resolved_memory = memory_pool or self.build_memory_pool()
        resolved_context = context_engine or self.build_context_engine(resolved_memory)
        resolved_agent = agent_service or self.build_agent_service(resolved_llm)
        qq = self.section("qq")
        allowed_group_ids = set(self._pick_int_list(qq, "allowed_group_ids", env_key="QQ_ALLOWED_GROUP_IDS"))
        return Router(
            llm_service=resolved_llm,
            agent_service=resolved_agent,
            memory_pool=resolved_memory,
            context_engine=resolved_context,
            allowed_group_ids=allowed_group_ids,
        )

    def build_message_workflow(
        self,
        *,
        router: Router | None = None,
        context_engine: ContextEngine | None = None,
    ) -> MessageWorkflow:
        resolved_router = router or self.build_router(context_engine=context_engine)
        resolved_context = context_engine or resolved_router.context_engine
        return MessageWorkflow(
            router=resolved_router,
            context_engine=resolved_context,
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

    def _pick_float_in_range(
        self,
        section: dict[str, Any],
        key: str,
        *,
        env_key: str | None = None,
        default: float,
        min_value: float,
        max_value: float,
    ) -> float:
        value: Any = section.get(key)
        if value is None and env_key:
            value = os.getenv(env_key)
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return min(max(parsed, min_value), max_value)

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

    def _pick_int_list(
        self,
        section: dict[str, Any],
        key: str,
        *,
        env_key: str | None = None,
    ) -> list[int]:
        value: Any = section.get(key)
        if value is None and env_key:
            value = os.getenv(env_key)

        items: list[Any]
        if isinstance(value, str):
            items = [part.strip() for part in value.split(",")]
        elif isinstance(value, list):
            items = value
        else:
            return []

        parsed: list[int] = []
        for item in items:
            try:
                group_id = int(item)
            except (TypeError, ValueError):
                continue
            if group_id > 0:
                parsed.append(group_id)
        return parsed
