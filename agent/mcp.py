from __future__ import annotations
import json
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional


class MCPClient:
    def __init__(self, command: str, args: Optional[List[str]] = None, timeout: int = 30):
        self.proc = subprocess.Popen(
            [command] + (args or []),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        self.timeout = timeout
        self._id = 0
        self._lock = threading.Lock()
        self._responses: Dict[int, dict] = {}
        self._notifications: List[dict] = []
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in obj and ("result" in obj or "error" in obj):
                self._responses[obj["id"]] = obj
            else:
                self._notifications.append(obj)

    def _request(self, method: str, params: Any):
        with self._lock:
            self._id += 1
            mid = self._id
            msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if mid in self._responses:
                r = self._responses.pop(mid)
                if "error" in r:
                    raise RuntimeError(r["error"])
                return r["result"]
            time.sleep(0.01)
        raise TimeoutError(method)

    def initialize(self):
        return self._request(
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {},
             "clientInfo": {"name": "ideal-agent", "version": "0.1"}},
        )

    def list_tools(self) -> List[dict]:
        return self._request("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict):
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def close(self):
        try:
            self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "shutdown"}) + "\n")
            self.proc.stdin.flush()
        except OSError:
            pass
        self.proc.terminate()
