from dataclasses import dataclass, field
from typing import Any

from src.agent import AgentService
from src.context import ContextEngine
from src.llm import LLMService
from src.memory import MemoryPool
from src.prompting import ReplyMode

from .structured_service import StructuredService


@dataclass(slots=True)
class StructuredCommand:
    name: str
    args: dict[str, Any] = field(default_factory=dict)


class Router:
    """Router component for handling user input and structured commands."""

    def __init__(
        self,
        structured_service: StructuredService | None = None,
        agent_service: AgentService | None = None,
        llm_service: LLMService | None = None,
        memory_pool: MemoryPool | None = None,
        context_engine: ContextEngine | None = None,
        allowed_group_ids: set[int] | None = None,
    ) -> None:
        self._structured_service = structured_service or StructuredService()
        self._llm_service = llm_service or LLMService()
        self._agent_service = agent_service or AgentService(llm_service=self._llm_service)
        self._memory_pool = memory_pool or MemoryPool()
        self._context_engine = context_engine or ContextEngine(memory_pool=self._memory_pool)
        self._allowed_group_ids = set(allowed_group_ids or set())

    def route(
        self,
        msg: str | None = None,
        *,
        at_user: bool = False,
        command: StructuredCommand | None = None,
    ) -> str | None:
        """Unified entry for normal message, @ input, and structured command."""
        if command is not None:
            return self.handle_structured(command)

        clean = self.normalize_text(msg)
        if clean is None:
            return None

        if at_user:
            return self._handle_at_message(clean)

        return self._handle_message(clean)

    def normalize_text(self, msg: str | None) -> str | None:
        if msg is None:
            return None
        clean = msg.strip()
        return clean or None

    def should_process_message(self, *, source: str, group_id: int | None) -> bool:
        if source != "qq_group":
            return True
        if not self._allowed_group_ids:
            return True
        if group_id is None:
            return False
        return group_id in self._allowed_group_ids

    def process_agent(
        self,
        content: str,
        *,
        is_at_message: bool,
        reply_mode: ReplyMode = "auto",
    ) -> str:
        return self._agent_service.process_input(
            content,
            is_at_message=is_at_message,
            reply_mode=reply_mode,
        )

    def handle_structured(self, command: StructuredCommand) -> str:
        return self._handle_structured_command(command)

    @property
    def context_engine(self) -> ContextEngine:
        return self._context_engine

    def _handle_message(self, msg: str) -> str | None:
        return self._context_engine.handle_usr_msg(
            msg,
            is_direct_to_ai=False,
            processor=lambda content: self.process_agent(
                content,
                is_at_message=False,
                reply_mode="auto",
            ),
        )

    def _handle_at_message(self, msg: str) -> str:
        result = self._context_engine.handle_usr_msg(
            msg,
            is_direct_to_ai=True,
            processor=lambda content: self.process_agent(
                content,
                is_at_message=True,
                reply_mode="tense",
            ),
        )
        return result or "输入不能为空。"

    def _handle_structured_command(self, command: StructuredCommand) -> str:
        if command.name == "help":
            return self._structured_service.handle_help()
        if command.name == "ping":
            return self._structured_service.handle_ping()
        if command.name == "mcp_tools":
            tools = self._agent_service.list_mcp_tools()
            return self._structured_service.handle_mcp_tools(tools)

        return f"不支持的命令: {command.name}"
