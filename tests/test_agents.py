import json
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.agents import OpenAIAgentRuntime, agent_specs


class _Responses:
    def __init__(self, calls): self.calls = calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=json.dumps({"ok": True}), id="resp-test", usage=None,
        )


class _Client:
    def __init__(self, calls): self.responses = _Responses(calls)


class AgentRuntimeTests(TestCase):
    def test_all_three_roles_default_to_luna_medium(self):
        specs = agent_specs()
        self.assertEqual(set(specs), {"editing", "repair", "learning"})
        for spec in specs.values():
            self.assertEqual(spec.model, "gpt-5.6-luna")
            self.assertEqual(spec.reasoning_effort, "medium")

    def test_runtime_sends_role_model_reasoning_and_strict_schema(self):
        calls = []
        runtime = OpenAIAgentRuntime(client_factory=lambda **kwargs: _Client(calls))
        schema = {"type": "object", "additionalProperties": False,
                  "required": ["ok"], "properties": {"ok": {"type": "boolean"}}}
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            result, metadata = runtime.run_structured("repair", "repair", schema, "Fix it")
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0]["model"], "gpt-5.6-luna")
        self.assertEqual(calls[0]["reasoning"], {"effort": "medium"})
        self.assertTrue(calls[0]["text"]["format"]["strict"])
        self.assertEqual(metadata["agent_key"], "repair")
        self.assertEqual(metadata["agent_role_version"], "timeline-repair-agent-v1")


if __name__ == "__main__":
    import unittest
    unittest.main()
