from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(slots=True)
class LLMService:
    """Process user input and return API service result."""

    api_url: str | None = None
    api_key: str | None = None
    timeout: float = 15.0
    model: str = "default"

    def __post_init__(self) -> None:
        if self.api_url is None:
            self.api_url = os.getenv("LLM_API_URL")
        if self.api_key is None:
            self.api_key = os.getenv("LLM_API_KEY")

    def process_input(self, content: str, *, is_at_message: bool = False) -> str:
        """Send content to LLM API and return response text."""
        if not content.strip():
            return "输入不能为空。"

        if not self.api_url:
            return "未配置 LLM API 地址（LLM_API_URL）。"

        payload: dict[str, Any] = {
            "model": self.model,
            "input": content,
            "meta": {"at_user": is_at_message},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            url=self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            return f"LLM API 请求失败: HTTP {exc.code} {detail}".strip()
        except URLError as exc:
            return f"LLM API 请求失败: {exc.reason}"

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return raw.strip() or "LLM API 返回为空。"

        if isinstance(parsed, dict):
            for key in ("output", "result", "message", "text"):
                value = parsed.get(key)
                if isinstance(value, str):
                    return value

        return raw.strip() or "LLM API 返回为空。"
