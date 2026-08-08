import sys
import json
import re
import urllib.request
import urllib.error


def web_fetch(url: str) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ideal-agent/0.1"})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
        enc = r.headers.get_content_charset() or "utf-8"
        html = raw.decode(enc, errors="replace")
    except Exception as e:
        return f"error: {e}"
    html = re.sub(r"(?is)<(script|style|head|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?is)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:8000]


def handle(method: str, params: dict) -> dict:
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "fetch", "version": "0.1"}}
    if method == "tools/list":
        return {"tools": [{
            "name": "web_fetch",
            "description": "Загрузить текст веб-страницы по URL.",
            "inputSchema": {"type": "object",
                            "properties": {"url": {"type": "string"}},
                            "required": ["url"]},
        }]}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "web_fetch":
            return {"content": [{"type": "text", "text": web_fetch(args.get("url", ""))[:4000]}]}
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
            json.dumps({"jsonrpc": "2.0", "id": mid, "result": handle(method, msg.get("params", {}))}) + "\n"
        )
        sys.stdout.flush()
