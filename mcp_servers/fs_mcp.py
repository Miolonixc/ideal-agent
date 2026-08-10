from __future__ import annotations
import sys
import json
import os


def read_file(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"error: {e}"


def handle(method: str, params: dict) -> dict:
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "serverInfo": {"name": "fs", "version": "0.1"},
        }
    if method == "tools/list":
        return {
            "tools": [
                {
                    "name": "read_file",
                    "description": "Прочитать файл по пути.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                }
            ]
        }
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "read_file":
            return {"content": [{"type": "text", "text": read_file(args.get("path", ""))[:4000]}]}
        return {"content": [{"type": "text", "text": "unknown tool"}]}
    return {}


for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = msg.get("method")
    mid = msg.get("id")
    if method and mid is not None:
        sys.stdout.write(
            json.dumps({"jsonrpc": "2.0", "id": mid, "result": handle(method, msg.get("params", {}))})
            + "\n"
        )
        sys.stdout.flush()
