from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.heartbeat import HeartbeatMonitor
from src.memory import MemoryPool


@dataclass(slots=True)
class ContextEngine:
    """Manage only recent context and delegate long-term memory to MemoryPool."""

    memory_pool: MemoryPool
    heartbeat_monitor: HeartbeatMonitor = field(default_factory=HeartbeatMonitor)
    recent_limit: int = 100
    _recent_context: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        self._recent_context = self.memory_pool.recent(self.recent_limit)

    def handle_usr_msg(
        self,
        usr_msg: str,
        *,
        is_direct_to_ai: bool,
        processor: Callable[[str], str],
    ) -> str | None:
        """
        Process user message by rule:
        - direct-to-ai: always process
        - non-direct: process by heartbeat state machine
        """
        clean_msg = usr_msg.strip()
        if not clean_msg:
            return None

        should_call = self.heartbeat_monitor.should_invoke_llm(
            clean_msg,
            is_at_message=is_direct_to_ai,
        )
        if not should_call:
            self.remember_user_message(clean_msg)
            return None

        composed = self.compose_input(clean_msg)
        self.remember_user_message(clean_msg)
        reply = processor(composed)
        self.remember_assistant_message(reply)
        self.heartbeat_monitor.on_llm_invoked(clean_msg, reply)
        return reply

    def compose_input(self, current_msg: str) -> str:
        history = self._recent_context
        if not history:
            return current_msg

        return (
            "你可以参考以下对话记忆来回答问题。\n"
            "对话记忆:\n"
            f"{'\n'.join(history)}\n"
            f"当前用户输入:\n{current_msg}"
        )

    def remember_user_message(self, msg: str) -> None:
        clean = msg.strip()
        if not clean:
            return
        self._remember(f"user: {clean}")

    def remember_assistant_message(self, msg: str) -> None:
        clean = msg.strip()
        if not clean:
            return
        self._remember(f"assistant: {clean}")

    def _remember(self, item: str) -> None:
        self.memory_pool.append(item)
        self._recent_context.append(item)
        if len(self._recent_context) > self.recent_limit:
            self._recent_context = self._recent_context[-self.recent_limit :]
