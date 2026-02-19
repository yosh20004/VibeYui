from __future__ import annotations

import os
from dataclasses import dataclass, field

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI

from src.prompting import PromptContext, PromptManager, ReplyMode


@dataclass(slots=True)
class LLMService:
    """Process user input and return API service result."""

    api_url: str | None = None
    api_key: str | None = None
    timeout: float = 15.0
    model: str = "default"
    temperature: float = 2.0
    prompt_manager: PromptManager = field(default_factory=PromptManager.default)

    def __post_init__(self) -> None:
        if self.api_url is None:
            self.api_url = os.getenv("LLM_API_URL")
        if self.api_key is None:
            self.api_key = os.getenv("LLM_API_KEY")

    def process_input(
        self,
        content: str,
        *,
        is_at_message: bool = False,
        reply_mode: ReplyMode = "auto",
    ) -> str:
        """Send content to LLM API and return response text."""
        if not content.strip():
            return "输入不能为空。"

        messages = self.prompt_manager.build_messages(
            content,
            context=PromptContext(mode=reply_mode, is_at_message=is_at_message),
        )
        return self._request_completion(
            messages,
            is_at_message=is_at_message,
            reply_mode=reply_mode,
            temperature=self.temperature,
        )

    def process_input_with_system(
        self,
        content: str,
        *,
        system_prompt: str,
        is_at_message: bool = False,
        reply_mode: ReplyMode = "auto",
        temperature: float | None = None,
    ) -> str:
        if not content.strip():
            return "输入不能为空。"
        if not system_prompt.strip():
            return self.process_input(
                content,
                is_at_message=is_at_message,
                reply_mode=reply_mode,
            )

        messages = [
            {"role": "system", "content": system_prompt.strip()},
            {"role": "user", "content": content},
        ]
        return self._request_completion(
            messages,
            is_at_message=is_at_message,
            reply_mode=reply_mode,
            temperature=self.temperature if temperature is None else temperature,
        )

    def _request_completion(
        self,
        messages: list[dict[str, str]],
        *,
        is_at_message: bool,
        reply_mode: ReplyMode,
        temperature: float,
    ) -> str:
        if not self.api_url:
            return "未配置 LLM API 地址（LLM_API_URL）。"

        try:
            client = OpenAI(
                api_key=self.api_key or None,
                base_url=self.api_url,
                timeout=self.timeout,
            )
            response = client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                extra_body={"meta": {"at_user": is_at_message, "reply_mode": reply_mode}},
            )
        except APIStatusError as exc:
            body = ""
            try:
                body = str(exc.response.text).strip()
            except Exception:
                body = str(exc).strip()
            return f"LLM API 请求失败: HTTP {exc.status_code} {body}".strip()
        except (APITimeoutError, APIConnectionError) as exc:
            return f"LLM API 请求失败: {exc}"
        except Exception as exc:
            return f"LLM API 请求失败: {exc}"

        try:
            text = response.choices[0].message.content
        except Exception:
            text = None

        if isinstance(text, str) and text.strip():
            return text
        return "LLM API 返回为空。"
