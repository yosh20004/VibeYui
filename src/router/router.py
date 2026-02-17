from dataclasses import dataclass, field
from typing import Any

from src.context import ContextEngine
from src.llm import LLMService
from src.memory import MemoryPool

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
        llm_service: LLMService | None = None,
        memory_pool: MemoryPool | None = None,
        context_engine: ContextEngine | None = None,
    ) -> None:
        self._structured_service = structured_service or StructuredService()
        self._llm_service = llm_service or LLMService()
        self._memory_pool = memory_pool or MemoryPool()
        self._context_engine = context_engine or ContextEngine(memory_pool=self._memory_pool)

    def route(
        self,
        msg: str | None = None,
        *,
        at_user: bool = False,
        command: StructuredCommand | None = None,
    ) -> str | None:
        """Unified entry for normal message, @ input, and structured command."""
        if command is not None:
            return self._handle_structured_command(command)

        if msg is None:
            return None

        if at_user:
            return self._handle_at_message(msg)

        return self._handle_message(msg)

    def _handle_message(self, msg: str) -> str | None:
        return self._context_engine.handle_usr_msg(
            msg,
            is_direct_to_ai=False,
            processor=lambda content: self._llm_service.process_input(
                content,
                is_at_message=False,
            ),
        )

    def _handle_at_message(self, msg: str) -> str:
        result = self._context_engine.handle_usr_msg(
            msg,
            is_direct_to_ai=True,
            processor=lambda content: self._llm_service.process_input(
                content,
                is_at_message=True,
            ),
        )
        return result or "输入不能为空。"

    def _handle_structured_command(self, command: StructuredCommand) -> str:
        if command.name == "help":
            return self._structured_service.handle_help()
        if command.name == "ping":
            return self._structured_service.handle_ping()

        return f"不支持的命令: {command.name}"
