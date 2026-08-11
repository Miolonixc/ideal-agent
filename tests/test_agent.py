from __future__ import annotations
import json
import io
import os
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

from agent.config import AgentConfig, load, save_runtime_settings
from agent.core import Agent
from agent.llm import OpenAICompatible, ProviderError
from agent.memory import RepoIndex, MemoryStore, workspace_namespace
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
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as f:
            json.dump({"llm": {"provider": "openai-compatible"}}, f)
            f.flush()
            with mock.patch.dict(os.environ, {"TOKENROUTER_API_KEY": "sk-x"}, clear=True):
                cfg = load(f.name)
        self.assertEqual(cfg.llm.api_key, "sk-x")
        self.assertEqual(cfg.llm.model, "openrouter/free")

    def test_provider_specific_env_key(self):
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk-test"}, clear=True):
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as f:
                json.dump({"llm": {"provider": "groq"}}, f)
                f.flush()
                cfg = load(f.name)
        self.assertEqual(cfg.llm.api_key, "gsk-test")

    def test_save_runtime_settings_preserves_api_key_and_extra_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"llm": {"api_key": "keep-me", "custom": "value"}, "other": True}, f)
            cfg = AgentConfig()
            cfg.llm.model = "new-model"
            cfg.mode = "suggest"
            cfg.trusted_extensions = ["skill:lint"]
            cfg.extension_permissions = ["shell"]
            save_runtime_settings(cfg, path)
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
        self.assertEqual(saved["llm"]["api_key"], "keep-me")
        self.assertEqual(saved["llm"]["custom"], "value")
        self.assertEqual(saved["llm"]["model"], "new-model")
        self.assertTrue(saved["other"])
        self.assertEqual(saved["trusted_extensions"], ["skill:lint"])
        self.assertEqual(saved["extension_permissions"], ["shell"])


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

    def test_retries_only_temporary_http_errors(self):
        err = urllib.error.HTTPError("https://x/v1", 429, "busy", {}, io.BytesIO(b"try later"))
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":"ok"}}]}'
        with mock.patch("urllib.request.urlopen") as urlopen, mock.patch("time.sleep") as sleep:
            urlopen.side_effect = [err, response]
            p = OpenAICompatible("https://x/v1", "key", "model")
            self.assertEqual(p.complete([{"role": "user", "content": "hi"}])["choices"][0]["message"]["content"], "ok")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_network_error_is_normalized_without_retry(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")) as urlopen:
            p = OpenAICompatible("https://x/v1", "key", "model")
            with self.assertRaisesRegex(ProviderError, "не удалось подключиться"):
                p.complete([{"role": "user", "content": "hi"}])
        self.assertEqual(urlopen.call_count, 1)

    def test_empty_and_incomplete_stream_are_provider_errors(self):
        p = OpenAICompatible("https://x/v1", "key", "model")
        with self.assertRaisesRegex(ProviderError, "пустой ответ"):
            with mock.patch("urllib.request.urlopen") as urlopen:
                urlopen.return_value.__enter__.return_value.read.return_value = b'{"choices": []}'
                p.complete([{"role": "user", "content": "hi"}])
        with self.assertRaisesRegex(ProviderError, "оборванный SSE"):
            p._parse_sse('data: {"choices":[{"delta":{"content":"hi"}}]}\n')


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

    def test_close_releases_resources(self):
        agent = Agent(AgentConfig(workspace=tempfile.mkdtemp()))
        agent._ensure_context()
        agent.close()
        agent.close()  # shutdown is idempotent
        with self.assertRaises(Exception):
            agent.audit.conn.execute("SELECT 1")

    def test_agent_can_run_from_http_handler_thread(self):
        """Agent is built by main(), while ThreadingHTTPServer runs it elsewhere."""
        agent = Agent(AgentConfig(workspace=tempfile.mkdtemp(), mode="full-auto"))
        agent.provider = fake_provider_sequence([
            {"choices": [{"message": {"role": "assistant", "content": "ok"}}]},
        ])
        output = []
        worker = threading.Thread(target=lambda: output.append(agent.run("ping")))
        worker.start()
        worker.join(timeout=5)
        agent.close()
        self.assertEqual(output, ["ok"])

    def test_health_and_audit_commands(self):
        agent = Agent(AgentConfig(workspace=tempfile.mkdtemp()))
        agent.audit.record("allow", "echo", {}, "ok")
        self.assertIn("status: ok", agent.command("/health"))
        self.assertIn("allow echo", agent.command("/audit 1"))
        self.assertIn("используй", agent.command("/audit many"))
        agent.close()


class TestMemory(unittest.TestCase):
    def test_workspace_namespace_is_canonical_and_distinct(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as other:
            self.assertEqual(workspace_namespace(d), workspace_namespace(os.path.join(d, ".")))
            self.assertNotEqual(workspace_namespace(d), workspace_namespace(other))

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
    def test_rejects_tool_name_collision(self):
        reg = ToolRegistry()
        reg.register("same", "", {"type": "object"}, lambda args: "one")
        with self.assertRaisesRegex(ValueError, "already registered"):
            reg.register("same", "", {"type": "object"}, lambda args: "two")

    def test_workspace_sandbox(self):
        tmp = tempfile.mkdtemp()
        reg = ToolRegistry()
        builtin_tools.register_builtin_tools(reg, AgentConfig(workspace=tmp))
        p = os.path.join(tmp, "f.txt")
        self.assertIn("записано", reg.call("write_file", json.dumps({"path": p, "content": "x"})))
        self.assertIn("x", reg.call("read_file", json.dumps({"path": p})))
        self.assertIn("запрещена", reg.call("read_file", json.dumps({"path": "/etc/passwd"})))
        self.assertIn("запрещена", reg.call("grep", json.dumps({"pattern": ".", "path": "/etc"})))

    def test_rejects_invalid_tool_arguments(self):
        reg = ToolRegistry()
        reg.register("sample", "", {
            "type": "object", "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        }, lambda args: "ok")
        self.assertIn("отсутствует", reg.call("sample", "{}"))
        self.assertIn("должно иметь тип", reg.call("sample", '{"count":"one"}'))
        self.assertEqual("ok", reg.call("sample", '{"count":1}'))

    def test_truncates_tool_output(self):
        reg = ToolRegistry()
        reg.register("large", "", {"type": "object", "properties": {}}, lambda args: "x" * 20_000)
        self.assertIn("результат обрезан", reg.call("large", "{}"))


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
        self.assertEqual(reg.call("skill_hi", "{}"), "{}")

    def test_untrusted_script_is_visible_but_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            sd = os.path.join(tmp, "skills", "unsafe")
            os.makedirs(sd)
            with open(os.path.join(sd, "SKILL.md"), "w") as f:
                f.write("---\nname: unsafe\n---\n")
            with open(os.path.join(sd, "run.sh"), "w") as f:
                f.write("#!/bin/sh\necho executed\n")
            os.chmod(os.path.join(sd, "run.sh"), 0o755)
            reg = ToolRegistry()
            load_skills(reg, os.path.join(tmp, "skills"), trusted_extensions=[])
            self.assertIn("заблокировано", reg.call("skill_unsafe", "{}"))

    def test_skill_requires_declared_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            sd = os.path.join(tmp, "skills", "checked")
            os.makedirs(sd)
            with open(os.path.join(sd, "SKILL.md"), "w") as f:
                f.write("---\nname: checked\npermissions: filesystem, network\n---\n")
            with open(os.path.join(sd, "run.sh"), "w") as f:
                f.write("#!/bin/sh\necho ok\n")
            os.chmod(os.path.join(sd, "run.sh"), 0o755)
            reg = ToolRegistry()
            load_skills(reg, os.path.join(tmp, "skills"),
                        trusted_extensions=["skill:checked"], allowed_permissions=["shell"])
            self.assertIn("filesystem, network", reg.call("skill_checked", "{}"))
            reg = ToolRegistry()
            load_skills(reg, os.path.join(tmp, "skills"),
                        trusted_extensions=["skill:checked"],
                        allowed_permissions=["shell", "filesystem", "network"])
            self.assertEqual(reg.call("skill_checked", "{}"), "ok\n")


class TestMCP(unittest.TestCase):
    def test_agent_requires_explicit_mcp_trust(self):
        agent = Agent(AgentConfig(workspace=tempfile.mkdtemp()))
        with self.assertRaisesRegex(PermissionError, "не отмечен доверенным"):
            agent.connect_mcp("python3", ["mock.py"])
        agent.close()

    def test_client(self):
        tmp = tempfile.mkdtemp()
        server = os.path.join(tmp, "s.py")
        open(server, "w").write(MOCK_MCP)
        mc = MCPClient("python3", [server])
        mc.initialize()
        self.assertTrue(any(t["name"] == "echo" for t in mc.list_tools()))
        self.assertEqual(mc.call_tool("echo", {"text": "hi"})["content"][0]["text"], "hi")
        mc.close()
        with self.assertRaises(RuntimeError):
            mc.list_tools()

    def test_oversized_server_message_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = os.path.join(tmp, "too_large.py")
            with open(server, "w") as f:
                f.write("import sys\nprint('x' * 4096, flush=True)\nsys.stdin.read()\n")
            mc = MCPClient("python3", [server], timeout=1, max_message_bytes=1024)
            try:
                with self.assertRaisesRegex(RuntimeError, "превысил лимит"):
                    mc.initialize()
            finally:
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
