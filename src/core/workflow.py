from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.prompting import ReplyMode


class WorkflowHook(Protocol):
    """Pluggable hook for workflow lifecycle events."""

    def on_event(self, name: str, payload: dict[str, object]) -> None: ...


class ContextPort(Protocol):
    def heartbeat_snapshot(self, *, scope: str = "default") -> tuple[float, bool]: ...

    def should_invoke_llm(self, message: str, *, is_at_message: bool, scope: str = "default") -> bool: ...

    def on_llm_invoked(self, trigger_message: str, reply: str, *, scope: str = "default") -> None: ...

    def compose_input(self, current_msg: str, *, scope: str = "default") -> str: ...

    def remember_user_message(self, msg: str, *, scope: str = "default", user_name: str | None = None) -> None: ...

    def remember_assistant_message(self, msg: str, *, scope: str = "default") -> None: ...


class RouterPort(Protocol):
    def normalize_text(self, msg: str | None) -> str | None: ...

    def should_process_message(self, *, source: str, group_id: int | None) -> bool: ...

    def process_agent(self, content: str, *, is_at_message: bool, reply_mode: ReplyMode) -> str: ...

    def handle_structured(self, command: Any) -> str: ...


@dataclass(slots=True)
class LoggingHook:
    """Default workflow hook that prints workflow logs."""

    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("vibeyui.workflow"))

    def __post_init__(self) -> None:
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
        self.logger.propagate = False

    def on_event(self, name: str, payload: dict[str, object]) -> None:
        self.logger.info("[workflow] %s | %s", name, payload)


@dataclass(slots=True)
class MessageWorkflow:
    """Core workflow orchestrator.

    Pipeline:
    adapter -> router -> heartbeat -> context -> reply
    """

    router: RouterPort
    context_engine: ContextPort
    hooks: list[WorkflowHook] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.hooks:
            self.hooks.append(LoggingHook())

    def process(
        self,
        msg: str | None = None,
        *,
        at_user: bool = False,
        command: Any = None,
        source: str = "adapter",
        group_id: int | None = None,
        user_name: str | None = None,
    ) -> str | None:
        if command is not None:
            response = self.router.handle_structured(command)
            command_name = getattr(command, "name", "<unknown>")
            self._emit("router.command", {"source": source, "command": str(command_name)})
            return response

        if not self.router.should_process_message(source=source, group_id=group_id):
            self._emit(
                "adapter.ignore",
                {
                    "source": source,
                    "reason": "group_not_allowed",
                    "group_id": group_id,
                },
            )
            return None

        clean = self.router.normalize_text(msg)
        if clean is None:
            self._emit("adapter.ignore", {"source": source, "reason": "empty_message"})
            return None

        self._emit(
            "adapter.captured",
            {
                "source": source,
                "message": clean,
                "at_user": at_user,
                "group_id": group_id,
                "user_name": user_name,
            },
        )

        scope = self._scope(source=source, group_id=group_id)

        _, was_tense_before = self.context_engine.heartbeat_snapshot(scope=scope)
        should_reply = self.context_engine.should_invoke_llm(
            clean,
            is_at_message=at_user,
            scope=scope,
        )
        heartbeat_value, is_tense_now = self.context_engine.heartbeat_snapshot(scope=scope)
        reply_mode: ReplyMode = "tense" if (at_user or was_tense_before) else "auto"
        self._emit(
            "heartbeat.checked",
            {
                "should_reply": should_reply,
                "heartbeat": round(heartbeat_value, 2),
                "is_tense": is_tense_now,
                "reply_mode": reply_mode,
                "scope": scope,
            },
        )

        if not should_reply:
            self.context_engine.remember_user_message(clean, scope=scope, user_name=user_name)
            self._emit("context.user_recorded", {"reply": False})
            return None

        composed = self.context_engine.compose_input(clean, scope=scope)
        self.context_engine.remember_user_message(clean, scope=scope, user_name=user_name)
        self._emit("context.composed", {"has_history": "对话记忆" in composed})

        reply = self.router.process_agent(
            composed,
            is_at_message=at_user,
            reply_mode=reply_mode,
        )
        if not reply.strip():
            self._emit("workflow.no_reply", {"reason": "empty_reply"})
            return None

        self.context_engine.remember_assistant_message(reply, scope=scope)
        self.context_engine.on_llm_invoked(clean, reply, scope=scope)
        self._emit("workflow.replied", {"reply": reply})
        return reply

    def add_hooks(self, hooks: Sequence[WorkflowHook]) -> None:
        self.hooks.extend(hooks)

    def _emit(self, name: str, payload: dict[str, object]) -> None:
        for hook in self.hooks:
            try:
                hook.on_event(name, payload)
            except Exception:
                continue

    def _scope(self, *, source: str, group_id: int | None) -> str:
        if source == "qq_group" and group_id is not None:
            return f"qq_group_{group_id}"
        return source or "default"
