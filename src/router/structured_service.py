class StructuredService:
    """Structured command service."""

    def handle_help(self) -> str:
        return (
            "可用结构化命令:\n"
            "- help: 查看命令帮助\n"
            "- ping: 健康检查\n"
            "- mcp_tools: 查看 MCP 工具列表"
        )

    def handle_ping(self) -> str:
        return "pong"

    def handle_mcp_tools(self, tools: list[dict[str, object]]) -> str:
        if not tools:
            return "当前无可用 MCP 工具（可能未启用 MCP 或连接失败）。"

        lines = ["MCP 工具列表:"]
        for item in tools:
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                lines.append(f"- {name}")
        if len(lines) == 1:
            return "MCP 工具列表为空。"
        return "\n".join(lines)
