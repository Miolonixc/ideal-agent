import json
import os
import tempfile
import unittest
from unittest import mock

from agent.config import AgentConfig, load
from agent.core import Agent
from agent.llm import OpenAICompatible
from agent.memory import RepoIndex, MemoryStore
from agent.safety import ApprovalGate, AuditLog, make_diff
from agent.skills import load_skills
from agent.tools import ToolRegistry
from agent.mcp import MCPClient
from agent.subagents import run_subagent
from agent import builtin_tools


def fake_provider_sequence(sequence):
    class FakeP:
        model = "fake"

        def __init__(self):
            self.n = 0
            self.seq = sequence

        def complete(self, messages, tools=None, stream=False):
            self.n += 1
            return self.seq[self.n - 1]

        def count_tokens(self, text):
            return len(text) // 4
    return FakeP()


MOCK_MCP = '''import sys, json
for line in sys.stdin:
    line=line.strip()
    if not line: continue
    try: m=json.loads(line)
    except: continue
    method=m.get("method"); mid=m.get("id"); params=m.get("params",{})
    if method=="initialize":
        resp={"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"mock"}}}
    elif method=="tools/list":
        resp={"jsonrpc":"2.0","id":mid,"result":{"tools":[{"name":"echo","description":"e","inputSchema":{"type":"object","properties":{"text":{"type":"string"}}}}]}}
    elif method=="tools/call":
        resp={"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":params.get("arguments",{}).get("text","")}]}}
    else: continue
    sys.stdout.write(json.dumps(resp)+"\\n"); sys.stdout.flush()
'''


class TestConfig(unittest.TestCase):
    def test_env_key(self):
        with mock.patch.dict(os.environ, {"TOKENROUTER_API_KEY": "sk-x"}):
            cfg = load()
        self.assertTrue(cfg.llm.api_key)
        self.assertEqual(cfg.llm.model, "moonshotai/kimi-k3-free")


class TestLLM(unittest.TestCase):
    def test_sse_and_nonstream(self):
        sse = 'data: {"choices":[{"delta":{"content":"При"}}]}\ndata: {"choices":[{"delta":{"content":"вет"}}]}\ndata: [DONE]\n'
        with mock.patch("urllib.request.urlopen") as u:
            u.return_value.__enter__.return_value.read.return_value = sse.encode()
            p = OpenAICompatible("https://x/v1", "k", "m")
            self.assertEqual(p.complete([{"role": "user", "content": "hi"}], stream=True), "Привет")
            u.return_value.__enter__.return_value.read.return_value = json.dumps(
                {"choices": [{"message": {"content": "ок"}}]}).encode()
            self.assertEqual(p.complete([{"role": "user", "content": "hi"}])["choices"][0]["message"]["content"], "ок")


class TestCore(unittest.TestCase):
    def test_tool_loop(self):
        seq = [
            {"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "echo", "arguments": '{"text":"t"}'}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "готово"}}]},
        ]
        tmp = tempfile.mkdtemp()
        agent = Agent(AgentConfig(workspace=tmp, mode="full-auto"))
        agent.provider = fake_provider_sequence(seq)
        out = agent.run("go")
        self.assertEqual(out, "готово")
        self.assertIn("t", agent.history.messages[-2]["content"])


class TestMemory(unittest.TestCase):
    def test_repo_and_kv(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "a.py"), "w") as f:
            f.write("def query(sql):\n    return run(sql)\n")
        ri = RepoIndex(":memory:")
        ri.build(d)
        self.assertTrue(ri.search("query sql"))
        ms = MemoryStore(":memory:")
        ms.add("project", "stack", "проект на FastAPI и sqlite")
        self.assertIn("FastAPI", ms.recall("проект fastapi sqlite")[0]["text"])

    def test_extract_facts(self):
        class FakeP:
            model = "fake"
            def complete(self, messages, tools=None, stream=False):
                return {"choices": [{"message": {"role": "assistant",
                    "content": '["факт один","факт два"]'}}]}
            def count_tokens(self, t):
                return len(t) // 4
        ms = MemoryStore(":memory:")
        facts = ms.extract_facts("текст", FakeP())
        self.assertEqual(len(facts), 2)


class TestTools(unittest.TestCase):
    def test_workspace_sandbox(self):
        tmp = tempfile.mkdtemp()
        reg = ToolRegistry()
        builtin_tools.register_builtin_tools(reg, AgentConfig(workspace=tmp))
        p = os.path.join(tmp, "f.txt")
        self.assertIn("записано", reg.call("write_file", json.dumps({"path": p, "content": "x"})))
        self.assertIn("x", reg.call("read_file", json.dumps({"path": p})))
        self.assertIn("запрещена", reg.call("read_file", json.dumps({"path": "/etc/passwd"})))


class TestSafety(unittest.TestCase):
    def test_gate(self):
        g = ApprovalGate(mode="auto", deny=["shell:rm -rf"])
        self.assertEqual(g.decide("shell", '{"command":"rm -rf /"}')[0], "deny")
        self.assertEqual(g.decide("shell", '{"command":"ls"}')[0], "ask")
        self.assertEqual(g.decide("read_file", '{"path":"x"}')[0], "allow")
        AuditLog(":memory:").record("allow", "read_file", {}, "ok")
        self.assertTrue(make_diff("a=1", "a=2", "f.py"))


class TestSkills(unittest.TestCase):
    def test_load(self):
        tmp = tempfile.mkdtemp()
        sd = os.path.join(tmp, "skills", "hi")
        os.makedirs(sd)
        open(os.path.join(sd, "SKILL.md"), "w").write("---\nname: hi\ndescription: d\n---\nтекст\n")
        sp = os.path.join(sd, "run.sh")
        open(sp, "w").write("#!/bin/sh\ncat\n")
        os.chmod(sp, 0o755)
        reg = ToolRegistry()
        self.assertEqual(load_skills(reg, os.path.join(tmp, "skills")), ["hi"])


class TestMCP(unittest.TestCase):
    def test_client(self):
        tmp = tempfile.mkdtemp()
        server = os.path.join(tmp, "s.py")
        open(server, "w").write(MOCK_MCP)
        mc = MCPClient("python3", [server])
        mc.initialize()
        self.assertTrue(any(t["name"] == "echo" for t in mc.list_tools()))
        self.assertEqual(mc.call_tool("echo", {"text": "hi"})["content"][0]["text"], "hi")
        mc.close()


class TestChannels(unittest.TestCase):
    def test_cli(self):
        from agent.channels import CLIChannel, Message
        c = CLIChannel()
        c._argv = ["привет"]
        self.assertEqual(c.read().text, "привет")

    def test_telegram_filter(self):
        from agent.channels import TelegramChannel

        class MockTG(TelegramChannel):
            def _api(self, method, data=None):
                if method == "getUpdates":
                    return {"result": [{"update_id": 1, "message": {
                        "from": {"id": 77002359}, "chat": {"id": -1, "type": "group"},
                        "text": "x"}}]}
                return {}
        tg = MockTG("tok", allowed=[1])
        self.assertEqual(tg._poll_once(), [])


class TestSubagents(unittest.TestCase):
    def test_run(self):
        seq = [
            {"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "s1", "type": "function",
                                "function": {"name": "read_file",
                                             "arguments": '{"path":"/tmp/note.txt"}'}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "саб-ответ"}}]},
        ]
        tmp = tempfile.mkdtemp()
        open(os.path.join(tmp, "note.txt"), "w").write("данные")
        out = run_subagent("прочти", AgentConfig(workspace=tmp), fake_provider_sequence(seq), tools=["read_file"])
        self.assertIn("саб-ответ", out)


if __name__ == "__main__":
    unittest.main()
