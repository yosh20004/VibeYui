from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(slots=True)
class ContextEngine:
    """Manage short-term memory and route user messages by intent."""

    max_memory: int = 100
    context_window: int = 12
    _memory: list[str] = field(default_factory=list, init=False, repr=False)

    def handle_usr_msg(
        self,
        usr_msg: str,
        *,
        is_direct_to_ai: bool,
        processor: Callable[[str], str],
    ) -> str | None:
        """
        Process user message by rule:
        - direct-to-ai: process immediately
        - not direct-to-ai: only record
        """
        clean_msg = usr_msg.strip()
        if not clean_msg:
            return None

        if not is_direct_to_ai:
            self._remember(f"user: {clean_msg}")
            return None

        composed = self._compose_input(clean_msg)
        self._remember(f"user: {clean_msg}")
        reply = processor(composed)
        self._remember(f"assistant: {reply}")
        return reply

    def _compose_input(self, current_msg: str) -> str:
        history = self._memory[-self.context_window :]
        if not history:
            return current_msg

        return (
            "你可以参考以下对话记忆来回答问题。\n"
            "对话记忆:\n"
            f"{'\n'.join(history)}\n"
            f"当前用户输入:\n{current_msg}"
        )

    def _remember(self, item: str) -> None:
        self._memory.append(item)
        if len(self._memory) > self.max_memory:
            self._memory = self._memory[-self.max_memory :]
