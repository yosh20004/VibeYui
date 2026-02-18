from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ReplyMode = Literal["auto", "tense"]

_DEFAULT_PROMPT_JSON_PATH = Path("config/prompts.json")


@dataclass(slots=True, frozen=True)
class PromptContext:
    mode: ReplyMode
    is_at_message: bool


@dataclass(slots=True, frozen=True)
class PromptBundle:
    auto_system: str
    tense_extra: str
    tense_section_title: str = "【紧张模式补充】"

    @classmethod
    def from_json_file(cls, json_path: Path | None = None) -> PromptBundle:
        path = json_path or _DEFAULT_PROMPT_JSON_PATH
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid prompt config format in {path}")

        auto = _normalize_prompt_text(raw.get("auto_system"))
        tense = _normalize_prompt_text(raw.get("tense_extra"))
        if not auto or not tense:
            raise ValueError(f"Prompt config missing required fields in {path}")

        section = raw.get("tense_section_title")
        if not isinstance(section, str) or not section.strip():
            section = "【紧张模式补充】"
        return cls(
            auto_system=auto,
            tense_extra=tense,
            tense_section_title=section.strip(),
        )


@dataclass(slots=True)
class PromptManager:
    prompts: PromptBundle

    @classmethod
    def default(cls) -> PromptManager:
        return cls(prompts=PromptBundle.from_json_file())

    def system_prompt(self, *, context: PromptContext) -> str:
        if context.mode == "tense":
            return (
                f"{self.prompts.auto_system}\n\n"
                f"{self.prompts.tense_section_title}\n"
                f"{self.prompts.tense_extra}"
            )
        return self.prompts.auto_system

    def build_messages(self, user_content: str, *, context: PromptContext) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": self.system_prompt(context=context),
            },
            {
                "role": "user",
                "content": user_content,
            },
        ]


def _normalize_prompt_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        lines: list[str] = []
        for item in value:
            if isinstance(item, str):
                lines.append(item.rstrip("\n"))
        return "\n".join(lines).strip()
    return ""
