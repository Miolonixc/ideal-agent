from __future__ import annotations
import json
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional


MAX_MCP_MESSAGE_BYTES = 256 * 1024


class MCPClient:
    def __init__(self, command: str, args: Optional[List[str]] = None, timeout: int = 30,
                 max_message_bytes: int = MAX_MCP_MESSAGE_BYTES):
        self.command = command
        self.args = list(args or [])
        self.proc = subprocess.Popen(
            [command] + self.args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        self.timeout = timeout
        self.max_message_bytes = max(1024, max_message_bytes)
        self._id = 0
        self._lock = threading.Lock()
        self._responses_lock = threading.Lock()
        self._response_ready = threading.Condition(self._responses_lock)
        self._responses: Dict[int, dict] = {}
        self._notifications: List[dict] = []
        self._failed: Optional[str] = None
        self._closed = False
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self):
        while True:
            line = self.proc.stdout.readline(self.max_message_bytes + 1)
            if not line:
                break
            if len(line) > self.max_message_bytes:
                self._fail(f"MCP server превысил лимит сообщения ({self.max_message_bytes} байт)")
                return
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if "id" in obj and ("result" in obj or "error" in obj):
                with self._response_ready:
                    self._responses[obj["id"]] = obj
                    self._response_ready.notify_all()
            else:
                self._notifications.append(obj)
        if not self._closed and self.proc.poll() is not None:
            self._fail(f"MCP server завершился (код {self.proc.returncode})")

    def _fail(self, reason: str):
        with self._response_ready:
            if self._failed is None:
                self._failed = reason
            self._response_ready.notify_all()
        if self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass

    def _request(self, method: str, params: Any):
        if self._closed:
            raise RuntimeError("MCP client закрыт")
        if self._failed:
            raise RuntimeError(self._failed)
        if self.proc.poll() is not None:
            raise RuntimeError(f"MCP server завершился (код {self.proc.returncode})")
        with self._lock:
            self._id += 1
            mid = self._id
            msg = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}
            try:
                self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as e:
                raise RuntimeError(f"MCP server недоступен: {e}") from e
        deadline = time.monotonic() + self.timeout
        with self._response_ready:
            while time.monotonic() < deadline:
                if self._failed:
                    raise RuntimeError(self._failed)
                r = self._responses.pop(mid, None)
                if r is not None:
                    if "error" in r:
                        raise RuntimeError(r["error"])
                    return r["result"]
                self._response_ready.wait(timeout=max(0, deadline - time.monotonic()))
        self._notify("notifications/cancelled", {"requestId": mid, "reason": "timeout"})
        raise TimeoutError(f"MCP timeout: {method}")

    def _notify(self, method: str, params: Any):
        if self._closed or self.proc.poll() is not None:
            return
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            with self._lock:
                self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
                self.proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def initialize(self):
        from . import __version__
        return self._request(
            "initialize",
            {"protocolVersion": "2024-11-05", "capabilities": {},
             "clientInfo": {"name": "ideal-agent", "version": __version__}},
        )

    def list_tools(self) -> List[dict]:
        return self._request("tools/list", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict):
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def close(self):
        self._closed = True
        if self.proc.poll() is None:
            try:
                self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "shutdown"}).encode("utf-8") + b"\n")
                self.proc.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        for stream in (self.proc.stdin, self.proc.stdout):
            try:
                stream.close()
            except (OSError, ValueError):
                pass
        self._thread.join(timeout=1)
