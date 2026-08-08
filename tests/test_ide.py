from __future__ import annotations
import json
import socket
import threading
import time
import unittest

from agent.channels import SocketChannel, serve
from agent.config import AgentConfig
from agent.core import Agent


class TestIDEChannel(unittest.TestCase):
    def test_socket_roundtrip(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()

        class FakeP:
            model = "fake"

            def complete(self, messages, tools=None, stream=False):
                return {"choices": [{"message": {"role": "assistant",
                    "content": "ответ: " + messages[-1]["content"]}}]}

            def count_tokens(self, t):
                return len(t) // 4

        agent = Agent(AgentConfig(workspace="/tmp"))
        agent.provider = FakeP()
        channel = SocketChannel(port=port)

        result = {}

        def client():
            time.sleep(0.2)
            c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            c.connect(("127.0.0.1", port))
            f = c.makefile("rwb", buffering=0)
            f.write((json.dumps({"text": "привет"}) + "\n").encode())
            line = f.readline()
            result["reply"] = json.loads(line)["text"]
            c.close()

        t = threading.Thread(target=client)
        t.start()
        serve(channel, agent)  # returns after client closes
        t.join()
        self.assertEqual(result["reply"], "ответ: привет")


if __name__ == "__main__":
    unittest.main()
