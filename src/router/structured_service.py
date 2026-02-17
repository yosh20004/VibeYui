class StructuredService:
    """Structured command service."""

    def handle_help(self) -> str:
        return (
            "可用结构化命令:\n"
            "- help: 查看命令帮助\n"
            "- ping: 健康检查"
        )

    def handle_ping(self) -> str:
        return "pong"
