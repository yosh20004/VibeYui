from __future__ import annotations

import atexit
import asyncio
import dataclasses
import json
import os
import shlex
import threading
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from src.llm import LLMService
from src.prompting import ReplyMode


class MCPError(RuntimeError):
    """Raised when an MCP operation fails."""


@dataclass(slots=True)
class OfficialMCPClient:
    """Official MCP Python SDK based stdio client."""

    command: str
    request_timeout: float = 10.0
    startup_timeout: float = 15.0
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _loop: asyncio.AbstractEventLoop | None = field(default=None, init=False, repr=False)
    _session: Any = field(default=None, init=False, repr=False)
    _ready_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _stop_event: asyncio.Event | None = field(default=None, init=False, repr=False)
    _startup_error: str | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return

        self._ready_event.clear()
        self._startup_error = None
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        if not self._ready_event.wait(timeout=self.startup_timeout):
            raise MCPError("MCP 启动超时。")

        if self._startup_error is not None:
            raise MCPError(self._startup_error)

    def close(self) -> None:
        loop = self._loop
        stop_event = self._stop_event
        thread = self._thread

        if loop is not None and stop_event is not None:
            loop.call_soon_threadsafe(stop_event.set)

        if thread is not None:
            thread.join(timeout=2.0)

        self._thread = None

    def list_tools(self) -> list[dict[str, Any]]:
        response = self._call_async(self._list_tools_async())
        tools = getattr(response, "tools", [])
        result: list[dict[str, Any]] = []
        for tool in tools:
            plain = self._to_plain(tool)
            if isinstance(plain, dict):
                result.append(plain)
        return result

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._call_async(self._call_tool_async(name, arguments))
        plain = self._to_plain(response)
        if isinstance(plain, dict):
            return plain
        return {"value": plain}

    async def _list_tools_async(self) -> Any:
        if self._session is None:
            raise MCPError("MCP 会话未就绪。")
        return await self._session.list_tools()

    async def _call_tool_async(self, name: str, arguments: dict[str, Any]) -> Any:
        if self._session is None:
            raise MCPError("MCP 会话未就绪。")
        return await self._session.call_tool(name, arguments=arguments)

    def _call_async(self, coro: Any) -> Any:
        loop = self._loop
        thread = self._thread
        if loop is None or thread is None or not thread.is_alive():
            raise MCPError("MCP 客户端未启动。")

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=self.request_timeout)
        except Exception as exc:
            raise MCPError(f"MCP 调用失败: {exc}") from exc

    def _run_loop(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as exc:
            self._startup_error = f"MCP 启动失败: {exc}"
            self._ready_event.set()

    async def _main(self) -> None:
        argv = shlex.split(self.command)
        if not argv:
            raise MCPError("MCP_SERVER_CMD 为空，无法启动 MCP。")

        params = StdioServerParameters(
            command=argv[0],
            args=argv[1:],
            env=os.environ.copy(),
        )

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self._session = session
                self._loop = asyncio.get_running_loop()
                self._stop_event = asyncio.Event()
                self._ready_event.set()
                await self._stop_event.wait()

        self._session = None
        self._loop = None
        self._stop_event = None

    def _to_plain(self, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(k): self._to_plain(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_plain(item) for item in value]
        if dataclasses.is_dataclass(value):
            return self._to_plain(dataclasses.asdict(value))
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return self._to_plain(model_dump(mode="json", exclude_none=True))
            except TypeError:
                return self._to_plain(model_dump())
        return str(value)


@dataclass(slots=True)
class AgentService:
    """LLM agent orchestrator with optional MCP tool calling."""

    llm_service: LLMService
    mcp_client: OfficialMCPClient | None = None
    max_steps: int = 3
    final_reply_tool: str = "emit_reply"
    default_mcp_command: str = "python -m src.agent.mcp_servers.web_server"
    _cached_tools: list[dict[str, Any]] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.mcp_client is not None:
            self._start_mcp()
            return

        enabled = os.getenv("MCP_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
        server_cmd = os.getenv("MCP_SERVER_CMD", "").strip()
        if not enabled or not server_cmd:
            return

        timeout_raw = os.getenv("MCP_REQUEST_TIMEOUT", "10")
        try:
            timeout = max(1.0, float(timeout_raw))
        except ValueError:
            timeout = 10.0

        self.mcp_client = OfficialMCPClient(command=server_cmd, request_timeout=timeout)
        self._start_mcp()

    def process_input(
        self,
        content: str,
        *,
        is_at_message: bool = False,
        reply_mode: ReplyMode = "auto",
    ) -> str:
        if self.mcp_client is None:
            return self.llm_service.process_input(
                content,
                is_at_message=is_at_message,
                reply_mode=reply_mode,
            )

        if not self._cached_tools:
            try:
                self._cached_tools = self.mcp_client.list_tools()
            except MCPError:
                return self.llm_service.process_input(
                    content,
                    is_at_message=is_at_message,
                    reply_mode=reply_mode,
                )

        if not self._cached_tools:
            return self.llm_service.process_input(
                content,
                is_at_message=is_at_message,
                reply_mode=reply_mode,
            )

        return self._run_tool_loop(content, is_at_message=is_at_message, reply_mode=reply_mode)

    def list_mcp_tools(self) -> list[dict[str, Any]]:
        if self.mcp_client is None:
            return []
        try:
            self._cached_tools = self.mcp_client.list_tools()
        except MCPError:
            return []
        return self._cached_tools

    def _start_mcp(self) -> None:
        assert self.mcp_client is not None
        try:
            self.mcp_client.start()
        except MCPError:
            original = self.mcp_client
            fallback_cmd = self.default_mcp_command.strip()
            if fallback_cmd and original.command.strip() != fallback_cmd:
                fallback_client = OfficialMCPClient(
                    command=fallback_cmd,
                    request_timeout=original.request_timeout,
                    startup_timeout=original.startup_timeout,
                )
                try:
                    fallback_client.start()
                    self.mcp_client = fallback_client
                    atexit.register(self.mcp_client.close)
                    return
                except MCPError:
                    pass
            self.mcp_client = None
            self._cached_tools = []
            return
        atexit.register(self.mcp_client.close)

    def _run_tool_loop(
        self,
        content: str,
        *,
        is_at_message: bool,
        reply_mode: ReplyMode,
    ) -> str:
        tools_json = json.dumps(self._cached_tools, ensure_ascii=False)

        system_prompt = (
            "你是一个工具编排器，不负责直接输出给用户。"
            "你必须根据用户问题决定是否调用工具。"
            f"当你准备结束时，必须调用 `{self.final_reply_tool}` 工具来提交最终输出，"
            "并通过 should_reply=true/false 决定是否真的回复。"
            "每一轮只允许输出一个 JSON 对象，格式固定为:"
            '{"type":"tool_call","tool":"工具名","arguments":{...}}'
            "禁止输出 [TOOL_CALL] 包装、解释文字、Markdown 或任何额外文本。"
            "当调用最终回复工具时，arguments.content 必须符合聊天风格："
            "1-3 句话、尽量少于 80 字、自然随意、无标题无分点无 Markdown。"
        )

        prompt = (
            "可用工具:\n"
            f"{tools_json}\n\n"
            "用户问题:\n"
            f"{content}"
        )

        for _ in range(self.max_steps):
            raw = self.llm_service.process_input_with_system(
                prompt,
                system_prompt=system_prompt,
                is_at_message=is_at_message,
                reply_mode=reply_mode,
                temperature=0.2,
            )
            parsed = self._parse_json(raw)
            if not isinstance(parsed, dict):
                prompt = (
                    "你上一次输出不符合协议。"
                    "现在只能输出一个合法 JSON: "
                    '{"type":"tool_call","tool":"%s","arguments":{"content":"...","should_reply":true,"reason":"..."}}'
                    % self.final_reply_tool
                )
                continue

            if parsed.get("type") != "tool_call":
                prompt = (
                    "协议错误：type 必须是 tool_call。"
                    "请立即输出合法 JSON，并调用最终回复工具。"
                )
                continue

            tool_name = parsed.get("tool")
            arguments = parsed.get("arguments")
            if not isinstance(tool_name, str) or not tool_name.strip():
                prompt = (
                    "协议错误：tool 不能为空。"
                    f"请调用 `{self.final_reply_tool}` 并给出合法 arguments。"
                )
                continue
            if not isinstance(arguments, dict):
                arguments = {}

            try:
                tool_result = self.mcp_client.call_tool(tool_name, arguments)
            except MCPError as exc:
                prompt = (
                    "工具调用失败。请改用其他工具，或直接调用最终回复工具结束。"
                    f"\n失败原因: {exc}\n"
                    f"用户问题: {content}"
                )
                continue

            if tool_name == self.final_reply_tool:
                return self._extract_final_reply(tool_result, arguments)

            tool_result_text = json.dumps(tool_result, ensure_ascii=False)
            prompt = (
                "继续决策下一步。若信息已足够，请调用最终回复工具。"
                "输出格式仍然必须是 tool_call JSON。\n\n"
                f"用户问题: {content}\n"
                f"刚调用工具: {tool_name}\n"
                f"工具结果: {tool_result_text}"
            )

        # Enforce policy: without final reply tool call, do not reply.
        return ""

    def _extract_final_reply(self, tool_result: dict[str, Any], arguments: dict[str, Any]) -> str:
        extracted = self._extract_reply_payload(tool_result)
        if extracted is None:
            should_reply = bool(arguments.get("should_reply", True))
            if not should_reply:
                return ""
            content = arguments.get("content")
            return content.strip() if isinstance(content, str) else ""

        should_reply = extracted.get("should_reply")
        reply = extracted.get("reply")
        if should_reply is False:
            return ""
        if isinstance(reply, str):
            return reply.strip()
        return ""

    def _extract_reply_payload(self, value: Any) -> dict[str, Any] | None:
        candidate = self._find_reply_payload(value)
        if candidate is not None:
            return candidate
        if isinstance(value, dict):
            content = value.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str):
                            try:
                                parsed = json.loads(text)
                            except json.JSONDecodeError:
                                continue
                            candidate = self._find_reply_payload(parsed)
                            if candidate is not None:
                                return candidate
        return None

    def _find_reply_payload(self, value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            should_reply = value.get("should_reply")
            reply = value.get("reply")
            if isinstance(should_reply, bool) and (
                isinstance(reply, str) or reply is None
            ):
                return {"should_reply": should_reply, "reply": reply or ""}

            for nested in value.values():
                found = self._find_reply_payload(nested)
                if found is not None:
                    return found
            return None

        if isinstance(value, list):
            for item in value:
                found = self._find_reply_payload(item)
                if found is not None:
                    return found
        return None

    def _parse_json(self, raw: str) -> dict[str, Any] | None:
        text = raw.strip()
        if not text:
            return None

        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded
        except json.JSONDecodeError:
            pass

        # Compat for outputs like:
        # [TOOL_CALL]
        # {tool => "emit_reply", arguments => {...}}
        # [/TOOL_CALL]
        if "[TOOL_CALL]" in text and "[/TOOL_CALL]" in text:
            start_tag = text.find("[TOOL_CALL]")
            end_tag = text.rfind("[/TOOL_CALL]")
            if end_tag > start_tag:
                block = text[start_tag + len("[TOOL_CALL]") : end_tag].strip()
                block = block.replace("=>", ":")
                block = block.replace("{tool :", '{"tool":')
                block = block.replace(", arguments :", ', "arguments":')
                if not block.startswith("{"):
                    block = "{" + block
                if not block.endswith("}"):
                    block = block + "}"
                try:
                    loaded = json.loads(block)
                except json.JSONDecodeError:
                    loaded = None
                if isinstance(loaded, dict):
                    return {"type": "tool_call", **loaded}

        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None

        try:
            loaded = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None

        if isinstance(loaded, dict):
            return loaded
        return None
