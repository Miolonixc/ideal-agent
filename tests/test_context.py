from __future__ import annotations
import os
import tempfile
import unittest


class TestContext(unittest.TestCase):
    def test_context_injection(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "code.py"), "w") as f:
            f.write("def unique_function_xyz():\n    return 42\n")

        captured = {}

        class FakeP:
            model = "fake"

            def complete(self, messages, tools=None, stream=False):
                captured["messages"] = messages
                return {"choices": [{"message": {"role": "assistant",
                    "content": "нашёл"}}]}

            def count_tokens(self, t):
                return len(t) // 4

        from agent.config import AgentConfig
        from agent.core import Agent
        agent = Agent(AgentConfig(workspace=tmp, use_context=True))
        agent.provider = FakeP()
        out = agent.run("где unique_function_xyz?")
        self.assertEqual(out, "нашёл")
        msgs = captured["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("unique_function_xyz", msgs[0]["content"])
        self.assertIn("[file", msgs[0]["content"])

    def test_no_context_when_disabled(self):
        tmp = tempfile.mkdtemp()
        captured = {}

        class FakeP:
            model = "fake"

            def complete(self, messages, tools=None, stream=False):
                captured["messages"] = messages
                return {"choices": [{"message": {"role": "assistant", "content": "x"}}]}

            def count_tokens(self, t):
                return len(t) // 4

        from agent.config import AgentConfig
        from agent.core import Agent
        agent = Agent(AgentConfig(workspace=tmp, use_context=False))
        agent.provider = FakeP()
        agent.run("привет")
        systems = [m for m in captured["messages"] if m.get("role") == "system"]
        joined = " ".join(m["content"] for m in systems)
        self.assertNotIn("[file", joined)
        self.assertNotIn("[memory]", joined)


if __name__ == "__main__":
    unittest.main()
