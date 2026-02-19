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
    _recent_context_by_scope: dict[str, list[str]] = field(default_factory=dict, init=False, repr=False)
    _heartbeat_monitors: dict[str, HeartbeatMonitor] = field(default_factory=dict, init=False, repr=False)
    _heartbeat_template: HeartbeatMonitor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._heartbeat_template = self.heartbeat_monitor
        default_scope = self._normalize_scope(self._heartbeat_template.state_scope)
        self._heartbeat_monitors[default_scope] = self._heartbeat_template
        self._recent_context_by_scope = {}

    def handle_usr_msg(
        self,
        usr_msg: str,
        *,
        is_direct_to_ai: bool,
        scope: str = "default",
        user_name: str | None = None,
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

        should_call = self.should_invoke_llm(
            clean_msg,
            is_at_message=is_direct_to_ai,
            scope=scope,
        )
        if not should_call:
            self.remember_user_message(clean_msg, scope=scope, user_name=user_name)
            return None

        composed = self.compose_input(clean_msg, scope=scope)
        self.remember_user_message(clean_msg, scope=scope, user_name=user_name)
        reply = processor(composed)
        self.remember_assistant_message(reply, scope=scope)
        self.on_llm_invoked(clean_msg, reply, scope=scope)
        return reply

    def heartbeat_snapshot(self, *, scope: str = "default") -> tuple[float, bool]:
        monitor = self._heartbeat_for_scope(scope)
        return monitor.heartbeat, monitor.is_tense

    def should_invoke_llm(self, message: str, *, is_at_message: bool, scope: str = "default") -> bool:
        return self._heartbeat_for_scope(scope).should_invoke_llm(message, is_at_message=is_at_message)

    def on_llm_invoked(self, trigger_message: str, reply: str, *, scope: str = "default") -> None:
        self._heartbeat_for_scope(scope).on_llm_invoked(trigger_message, reply)

    def compose_input(self, current_msg: str, *, scope: str = "default") -> str:
        history = self._recent_context(scope)
        if not history:
            return current_msg

        return (
            "你可以参考以下对话记忆来回答问题。\n"
            "对话记忆:\n"
            f"{'\n'.join(history)}\n"
            f"当前用户输入:\n{current_msg}"
        )

    def remember_user_message(self, msg: str, *, scope: str = "default", user_name: str | None = None) -> None:
        clean = msg.strip()
        if not clean:
            return
        self._remember(f"user: {clean}", scope=scope, user_name=user_name)

    def remember_assistant_message(self, msg: str, *, scope: str = "default") -> None:
        clean = msg.strip()
        if not clean:
            return
        self._remember(f"assistant: {clean}", scope=scope)

    def _remember(self, item: str, *, scope: str, user_name: str | None = None) -> None:
        history = self._recent_context(scope)
        self.memory_pool.append(item, scope=scope, user_name=user_name)
        history.append(item)
        if len(history) > self.recent_limit:
            normalized_scope = self._normalize_scope(scope)
            self._recent_context_by_scope[normalized_scope] = history[-self.recent_limit :]

    def _recent_context(self, scope: str) -> list[str]:
        normalized_scope = self._normalize_scope(scope)
        if normalized_scope not in self._recent_context_by_scope:
            self._recent_context_by_scope[normalized_scope] = self.memory_pool.recent(
                self.recent_limit,
                scope=normalized_scope,
            )
        return self._recent_context_by_scope[normalized_scope]

    def _heartbeat_for_scope(self, scope: str) -> HeartbeatMonitor:
        normalized_scope = self._normalize_scope(scope)
        monitor = self._heartbeat_monitors.get(normalized_scope)
        if monitor is not None:
            return monitor

        template = self._heartbeat_template
        monitor = HeartbeatMonitor(
            max_heartbeat=template.max_heartbeat,
            wakeup_growth=template.wakeup_growth,
            idle_growth=template.idle_growth,
            tense_boost=template.tense_boost,
            tense_floor=template.tense_floor,
            tense_hold_seconds=template.tense_hold_seconds,
            state_store=template.state_store,
            state_scope=normalized_scope,
            _time_fn=template._time_fn,
        )
        self._heartbeat_monitors[normalized_scope] = monitor
        return monitor

    def _normalize_scope(self, scope: str) -> str:
        clean = scope.strip()
        if not clean:
            return "default"
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in clean)
