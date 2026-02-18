from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from .sqlite_store import HeartbeatSQLiteStore, HeartbeatState


@dataclass(slots=True)
class HeartbeatMonitor:
    """Heartbeat-based trigger state machine for passive LLM activation."""

    max_heartbeat: float = 100.0
    wakeup_growth: float = 6.0
    idle_growth: float = 2.0
    tense_boost: float = 24.0
    tense_floor: float = 60.0
    tense_hold_seconds: int = 15 * 60
    state_store: HeartbeatSQLiteStore | None = None
    state_scope: str = "default"
    _heartbeat: float = 0.0
    _tense: bool = False
    _focus_text: str = ""
    _tense_until_ts: int = 0
    _rng: random.Random = field(default_factory=random.Random, repr=False)
    _time_fn: Callable[[], float] = field(default=time.time, repr=False)

    def __post_init__(self) -> None:
        if self.state_store is None:
            return
        loaded = self.state_store.load(self.state_scope)
        if loaded is None:
            return
        self._heartbeat = min(self.max_heartbeat, max(0.0, loaded.heartbeat))
        self._tense = bool(loaded.is_tense)
        self._focus_text = loaded.focus_text.strip()
        self._tense_until_ts = int(loaded.tense_until_ts)
        self._refresh_tense_flag()

    @property
    def heartbeat(self) -> float:
        return self._heartbeat

    @property
    def is_tense(self) -> bool:
        return self._tense

    def should_invoke_llm(self, message: str, *, is_at_message: bool) -> bool:
        clean = message.strip()
        if not clean:
            return False

        if is_at_message:
            self._set_tense(clean)
            self._mark_tense_hold()
            self._persist()
            return True

        self._refresh_tense_flag()
        if self._tense:
            if self._is_hold_active():
                if self._is_related(clean):
                    self._set_tense(clean)
                    self._mark_tense_hold()
                self._persist()
                return True
            self._drop_to_zero()
            self._persist()
            return False

        self._grow_idle_heartbeat()
        trigger_prob = self._heartbeat / self.max_heartbeat
        if self._rng.random() < trigger_prob:
            self._set_tense(clean)
            self._persist()
            return True
        self._persist()
        return False

    def on_llm_invoked(self, trigger_message: str, reply: str) -> None:
        merged_focus = f"{trigger_message.strip()} {reply.strip()}".strip()
        self._set_tense(merged_focus)
        self._mark_tense_hold()
        self._persist()

    def _grow_idle_heartbeat(self) -> None:
        if self._heartbeat <= 0:
            self._heartbeat = min(self.max_heartbeat, self.wakeup_growth)
            return
        self._heartbeat = min(self.max_heartbeat, self._heartbeat + self.idle_growth)

    def _raise_heartbeat(self, delta: float) -> None:
        self._heartbeat = min(self.max_heartbeat, max(self._heartbeat, self.tense_floor) + delta)

    def _drop_to_zero(self) -> None:
        self._heartbeat = 0.0
        self._tense = False
        self._focus_text = ""
        self._tense_until_ts = 0

    def _set_tense(self, focus: str) -> None:
        self._tense = True
        self._focus_text = focus.strip()

    def _mark_tense_hold(self) -> None:
        self._tense_until_ts = int(self._time_fn()) + max(1, int(self.tense_hold_seconds))

    def _is_hold_active(self) -> bool:
        return self._tense_until_ts > 0 and int(self._time_fn()) < self._tense_until_ts

    def _refresh_tense_flag(self) -> None:
        if self._tense and self._tense_until_ts > 0 and not self._is_hold_active():
            self._drop_to_zero()

    def _persist(self) -> None:
        if self.state_store is None:
            return
        self.state_store.save(
            self.state_scope,
            HeartbeatState(
                heartbeat=self._heartbeat,
                is_tense=self._tense,
                focus_text=self._focus_text,
                tense_until_ts=self._tense_until_ts,
            ),
        )

    def _is_related(self, message: str) -> bool:
        if not self._focus_text:
            return True

        msg_words, msg_chars = self._collect_signals(message)
        focus_words, focus_chars = self._collect_signals(self._focus_text)

        if msg_words and focus_words and (msg_words & focus_words):
            return True
        if len(msg_chars & focus_chars) >= 2:
            return True
        return False

    def _collect_signals(self, text: str) -> tuple[set[str], set[str]]:
        lowered = text.lower()
        words = set(re.findall(r"[a-z0-9_]{2,}", lowered))
        cjk_chars = set(re.findall(r"[\u4e00-\u9fff]", lowered))
        return words, cjk_chars
