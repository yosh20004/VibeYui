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

    def process_input(self, content: str, *, is_at_message: bool = False) -> str:
        if self.mcp_client is None:
            return self.llm_service.process_input(content, is_at_message=is_at_message)

        if not self._cached_tools:
            try:
                self._cached_tools = self.mcp_client.list_tools()
            except MCPError:
                return self.llm_service.process_input(content, is_at_message=is_at_message)

        if not self._cached_tools:
            return self.llm_service.process_input(content, is_at_message=is_at_message)

        return self._run_tool_loop(content, is_at_message=is_at_message)

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
            self.mcp_client = None
            self._cached_tools = []
            return
        atexit.register(self.mcp_client.close)

    def _run_tool_loop(self, content: str, *, is_at_message: bool) -> str:
        tools_json = json.dumps(self._cached_tools, ensure_ascii=False)

        prompt = (
            "你是一个可以调用工具的助手。你必须先判断是否需要调用工具。"
            "如果需要工具，严格输出 JSON，格式:\n"
            '{"type":"tool_call","tool":"工具名","arguments":{...}}\n'
            "如果不需要工具，严格输出 JSON，格式:\n"
            '{"type":"final","content":"你的回答"}\n\n'
            "可用工具:\n"
            f"{tools_json}\n\n"
            "用户问题:\n"
            f"{content}"
        )

        for _ in range(self.max_steps):
            raw = self.llm_service.process_input(prompt, is_at_message=is_at_message)
            parsed = self._parse_json(raw)
            if not isinstance(parsed, dict):
                return raw

            if parsed.get("type") == "final":
                final_content = parsed.get("content")
                if isinstance(final_content, str) and final_content.strip():
                    return final_content
                return raw

            if parsed.get("type") != "tool_call":
                return raw

            tool_name = parsed.get("tool")
            arguments = parsed.get("arguments")
            if not isinstance(tool_name, str) or not tool_name.strip():
                return raw
            if not isinstance(arguments, dict):
                arguments = {}

            try:
                tool_result = self.mcp_client.call_tool(tool_name, arguments)
            except MCPError as exc:
                prompt = (
                    "工具调用失败。请直接给出无需工具的最终回答。"
                    f"\n失败原因: {exc}\n"
                    f"用户问题: {content}"
                )
                continue

            tool_result_text = json.dumps(tool_result, ensure_ascii=False)
            prompt = (
                "你已经拿到了工具结果，请基于结果回答用户。"
                "严格输出 JSON，格式:"
                '{"type":"final","content":"你的回答"}\n\n'
                f"用户问题: {content}\n"
                f"工具名: {tool_name}\n"
                f"工具结果: {tool_result_text}"
            )

        return self.llm_service.process_input(content, is_at_message=is_at_message)

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
