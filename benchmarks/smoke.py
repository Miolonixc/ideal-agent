import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.config import AgentConfig
from agent.core import Agent
from agent.llm import OpenAICompatible


class ScriptedProvider:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.calls = 0

    def complete(self, messages, tools=None, stream=False):
        self.calls += 1
        if self.scripted:
            return self.scripted.pop(0)
        return {"choices": [{"message": {"role": "assistant", "content": "done"}}]}

    def count_tokens(self, text):
        return len(text) // 4


def smoke():
    tmp = tempfile.mkdtemp()
    cfg = AgentConfig(workspace=tmp, mode="full-auto")
    agent = Agent(cfg)
    provider = ScriptedProvider([
        {"choices": [{"message": {"role": "assistant", "content": None,
            "tool_calls": [{"id": "1", "type": "function",
                            "function": {"name": "write_file",
                                         "arguments": '{"path": "%s/out.txt", "content": "hello"}' % tmp}}]}}]},
        {"choices": [{"message": {"role": "assistant", "content": "файл создан"}}]},
    ])
    agent.provider = provider
    start = time.time()
    out = agent.run("создай файл")
    elapsed = time.time() - start
    ok = os.path.exists(os.path.join(tmp, "out.txt")) and out == "файл создан"
    print(f"smoke: ok={ok} calls={provider.calls} time={elapsed:.3f}s")
    return ok


if __name__ == "__main__":
    raise SystemExit(0 if smoke() else 1)
