from __future__ import annotations

import unittest

from src.agent.service import AgentService


class FakeLLMService:
    def __init__(self, *, gate_response: str = "false", reply_response: str = "normal-reply") -> None:
        self.gate_response = gate_response
        self.reply_response = reply_response
        self.gate_calls = 0
        self.reply_calls = 0

    def process_input_with_system(self, content: str, **kwargs: object) -> str:
        self.gate_calls += 1
        return self.gate_response

    def process_input(self, content: str, **kwargs: object) -> str:
        self.reply_calls += 1
        return self.reply_response


class FakeMCPClient:
    def start(self) -> None:
        return

    def close(self) -> None:
        return

    def list_tools(self) -> list[dict[str, str]]:
        return [{"name": "emit_reply"}]

    def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        return {"should_reply": True, "reply": "tool-reply"}


class SpyAgentService(AgentService):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.tool_loop_calls = 0

    def _run_tool_loop(self, content: str, *, is_at_message: bool, reply_mode: str) -> str:
        self.tool_loop_calls += 1
        return "tool-loop-reply"


class AgentServicePassiveTenseGateTests(unittest.TestCase):
    def test_passive_tense_false_blocks_reply(self) -> None:
        llm = FakeLLMService(gate_response="false", reply_response="should-not-happen")
        service = AgentService(llm_service=llm)

        result = service.process_input("用户消息", is_at_message=False, reply_mode="tense")

        self.assertEqual("", result)
        self.assertEqual(1, llm.gate_calls)
        self.assertEqual(0, llm.reply_calls)

    def test_passive_tense_true_allows_reply(self) -> None:
        llm = FakeLLMService(gate_response="true", reply_response="ok")
        service = AgentService(llm_service=llm)

        result = service.process_input("用户消息", is_at_message=False, reply_mode="tense")

        self.assertEqual("ok", result)
        self.assertEqual(1, llm.gate_calls)
        self.assertEqual(1, llm.reply_calls)

    def test_non_passive_mode_skips_gate(self) -> None:
        llm = FakeLLMService(gate_response="false", reply_response="at-reply")
        service = AgentService(llm_service=llm)

        result = service.process_input("用户消息", is_at_message=True, reply_mode="tense")

        self.assertEqual("at-reply", result)
        self.assertEqual(0, llm.gate_calls)
        self.assertEqual(1, llm.reply_calls)

    def test_unknown_gate_output_defaults_to_false(self) -> None:
        llm = FakeLLMService(gate_response="maybe", reply_response="should-not-happen")
        service = AgentService(llm_service=llm)

        result = service.process_input("用户消息", is_at_message=False, reply_mode="tense")

        self.assertEqual("", result)
        self.assertEqual(1, llm.gate_calls)
        self.assertEqual(0, llm.reply_calls)

    def test_passive_tense_false_blocks_tool_loop_when_mcp_enabled(self) -> None:
        llm = FakeLLMService(gate_response="false", reply_response="should-not-happen")
        service = SpyAgentService(llm_service=llm, mcp_client=FakeMCPClient())

        result = service.process_input("用户消息", is_at_message=False, reply_mode="tense")

        self.assertEqual("", result)
        self.assertEqual(1, llm.gate_calls)
        self.assertEqual(0, llm.reply_calls)
        self.assertEqual(0, service.tool_loop_calls)


if __name__ == "__main__":
    unittest.main()
