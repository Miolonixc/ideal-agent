from __future__ import annotations
import sys
import os
import json
import urllib.request
import urllib.error


TOKEN = os.environ.get("GITHUB_TOKEN", "")


def _api(method, path, body=None):
    url = "https://api.github.com" + path
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "ideal-agent", "X-GitHub-Api-Version": "2022-11-28"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:400]}


def handle(method: str, params: dict) -> dict:
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {},
                "serverInfo": {"name": "github", "version": "0.1"}}
    if method == "tools/list":
        return {"tools": [
            {"name": "gh_list_issues", "description": "Список открытых issues репозитория.",
             "inputSchema": {"type": "object",
                             "properties": {"repo": {"type": "string"}},
                             "required": ["repo"]}},
            {"name": "gh_create_issue", "description": "Создать issue в репозитории.",
             "inputSchema": {"type": "object",
                             "properties": {"repo": {"type": "string"},
                                            "title": {"type": "string"},
                                            "body": {"type": "string"}},
                             "required": ["repo", "title"]}},
            {"name": "gh_list_repos", "description": "Список репозиториев пользователя.",
             "inputSchema": {"type": "object", "properties": {}}},
        ]}
    if method == "tools/call":
        name = params.get("name")
        a = params.get("arguments", {})
        if name == "gh_list_issues":
            res = _api("GET", f"/repos/{a.get('repo')}/issues?state=open&per_page=15")
            if isinstance(res, list):
                out = "\n".join(f"#{i['number']} {i['title']}" for i in res)
            else:
                out = f"error: {res}"
            return {"content": [{"type": "text", "text": out[:4000]}]}
        if name == "gh_create_issue":
            res = _api("POST", f"/repos/{a.get('repo')}/issues",
                       {"title": a.get("title"), "body": a.get("body", "")})
            if "error" in res:
                out = f"error: {res}"
            else:
                out = f"issue #{res.get('number')}: {res.get('html_url')}"
            return {"content": [{"type": "text", "text": out[:4000]}]}
        if name == "gh_list_repos":
            res = _api("GET", "/user/repos?per_page=30")
            if isinstance(res, list):
                out = "\n".join(r["full_name"] for r in res)
            else:
                out = f"error: {res}"
            return {"content": [{"type": "text", "text": out[:4000]}]}
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
