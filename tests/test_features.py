from __future__ import annotations
import sys
import json
import threading
import unittest
import urllib.request
import urllib.error

sys.path.insert(0, ".")

from agent.llm import get_provider
from agent.config import AgentConfig
from agent.core import Agent
from agent.channels import HTTPChannel


class FakeProvider:
    model = "fake"

    def complete(self, messages, tools=None, stream=False):
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    def count_tokens(self, t):
        return len(t) // 4


class TestProviders(unittest.TestCase):
    def test_construct_all(self):
        for prov, base, model in [
            ("openai-compatible", "https://x/v1", "m"),
            ("openrouter", "", ""),
            ("ollama", "", ""),
            ("anthropic", "", ""),
            ("gemini", "", ""),
        ]:
            c = AgentConfig()
            c.llm.provider = prov
            c.llm.base_url = base
            c.llm.model = model
            p = get_provider(c.llm)
            self.assertNotEqual(p, None)
            self.assertTrue(p.model)

    def test_unknown(self):
        c = AgentConfig()
        c.llm.provider = "nope"
        with self.assertRaises(ValueError):
            get_provider(c.llm)


class TestCommands(unittest.TestCase):
    def setUp(self):
        import tempfile
        cfg = AgentConfig(workspace=tempfile.mkdtemp(), mode="auto")
        cfg.use_context = False
        self.agent = Agent(cfg)

    def test_commands(self):
        self.assertIsNone(self.agent.command("обычный текст"))
        self.assertEqual(self.agent.command("/exit"), "__EXIT__")
        self.assertIn("режим", self.agent.command("/mode full-auto"))
        self.assertEqual(self.agent.gate.mode, "full-auto")
        self.assertIn("модель", self.agent.command("/status"))
        self.assertIn("навыки", self.agent.command("/skills"))
        self.assertIsNone(self.agent.command("/неизвестно"))


class TestGitHubWebhook(unittest.TestCase):
    def test_format(self):
        out = HTTPChannel._format_github("push", {
            "repository": {"full_name": "a/b"},
            "ref": "refs/heads/main",
            "commits": [{"message": "fix"}],
        })
        self.assertIn("a/b", out)
        self.assertIn("fix", out)


class TestHTTPChannel(unittest.TestCase):
    def test_live(self):
        import time
        import socket
        import tempfile
        cfg = AgentConfig(workspace=tempfile.mkdtemp(), mode="full-auto")
        cfg.use_context = False
        a = Agent(cfg)
        a.provider = FakeProvider()
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        port = srv.getsockname()[1]
        srv.close()
        ch = HTTPChannel(host="127.0.0.1", port=port, token="test-token")
        threading.Thread(target=ch.run, args=(a,), daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        # ждём готовности сервера
        for _ in range(50):
            try:
                urllib.request.urlopen(urllib.request.Request(
                    base + "/", headers={"X-Ideal-Agent-Token": "test-token"}
                ), timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(base + "/", timeout=5)
        self.assertEqual(denied.exception.code, 401)
        denied.exception.close()
        status = json.loads(urllib.request.urlopen(urllib.request.Request(
            base + "/", headers={"X-Ideal-Agent-Token": "test-token"}
        ), timeout=5).read())
        self.assertTrue(status["ok"])
        req = urllib.request.Request(
            base + "/message",
            data=json.dumps({"text": "привет"}).encode(),
            headers={"Content-Type": "application/json", "X-Ideal-Agent-Token": "test-token"}, method="POST",
        )
        res = json.loads(urllib.request.urlopen(req, timeout=10).read())
        self.assertEqual(res["reply"], "ok")


class TestStream(unittest.TestCase):
    def test_fallback_stream(self):
        import tempfile
        cfg = AgentConfig(workspace=tempfile.mkdtemp(), mode="full-auto")
        cfg.use_context = False
        a = Agent(cfg)
        a.provider = FakeProvider()  # нет stream_completion -> fallback
        out = list(a.stream("привет"))
        self.assertEqual(out, ["ok"])

    def test_streaming_provider(self):
        class StreamP:
            model = "fake"

            def stream_completion(self, messages, tools=None):
                yield ("content", "ра")
                yield ("content", "бот")
                # имитация tool_call
                yield ("tool", [{"id": "1", "type": "function",
                                 "function": {"name": "echo", "arguments": '{"text":"x"}'}}])

            def complete(self, messages, tools=None, stream=False):
                return {"choices": [{"message": {"role": "assistant", "content": "ра"}}]}

            def count_tokens(self, t):
                return 1

        import tempfile
        cfg = AgentConfig(workspace=tempfile.mkdtemp(), mode="full-auto")
        cfg.use_context = False
        a = Agent(cfg)
        a.provider = StreamP()
        out = list(a.stream("привет"))
        self.assertTrue(any("ра" in c for c in out))
        # после tool-call цикл продолжается и завершается fallback-куском
        self.assertTrue(len(out) >= 2)


class TestSkillsRun(unittest.TestCase):
    def test_make_tests_and_lint(self):
        import tempfile, os, subprocess
        d = tempfile.mkdtemp()
        src = os.path.join(d, "sample.py")
        open(src, "w").write("def add(a, b):\n    return a + b\n\nclass Foo:\n    def bar(self):\n        pass\n")
        skills_dir = os.path.join(os.path.dirname(__file__), "..", "skills")
        for skill, arg in [("make_tests", src), ("lint", src)]:
            script = os.path.join(skills_dir, skill, "run.sh")
            env = dict(os.environ)
            env["IDEAL_SKILL_INPUT"] = json.dumps({"input": arg})
            r = subprocess.run(["sh", script], env=env,
                               capture_output=True, text=True, cwd=os.path.join(skills_dir, skill))
            self.assertIn("создан", r.stdout + r.stderr) if skill == "make_tests" else None
            self.assertTrue(r.returncode == 0, r.stderr)
        test_file = os.path.join(d, "sample_test.py")
        self.assertTrue(os.path.isfile(test_file))
        self.assertIn("def test_add", open(test_file).read())


if __name__ == "__main__":
    unittest.main()
