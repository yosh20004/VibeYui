from __future__ import annotations

import random
import re
from dataclasses import dataclass, field


@dataclass(slots=True)
class HeartbeatMonitor:
    """Heartbeat-based trigger state machine for passive LLM activation."""

    max_heartbeat: float = 100.0
    wakeup_growth: float = 6.0
    idle_growth: float = 2.0
    tense_boost: float = 24.0
    tense_floor: float = 60.0
    _heartbeat: float = 0.0
    _tense: bool = False
    _focus_text: str = ""
    _rng: random.Random = field(default_factory=random.Random, repr=False)

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
            self._raise_heartbeat(self.tense_boost)
            return True

        if self._tense:
            if self._is_related(clean):
                self._set_tense(clean)
                self._raise_heartbeat(self.tense_boost)
                return True
            self._drop_to_zero()
            return False

        self._grow_idle_heartbeat()
        trigger_prob = self._heartbeat / self.max_heartbeat
        if self._rng.random() < trigger_prob:
            self._set_tense(clean)
            return True
        return False

    def on_llm_invoked(self, trigger_message: str, reply: str) -> None:
        merged_focus = f"{trigger_message.strip()} {reply.strip()}".strip()
        self._set_tense(merged_focus)
        self._raise_heartbeat(self.tense_boost)

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

    def _set_tense(self, focus: str) -> None:
        self._tense = True
        self._focus_text = focus.strip()

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
