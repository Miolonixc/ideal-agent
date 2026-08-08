#!/bin/sh
python3 - "$@" <<'PY'
import sys, json, os, urllib.request, urllib.error

raw = os.environ.get("IDEAL_SKILL_INPUT")
data = json.loads(raw) if raw else (json.load(sys.stdin) if not sys.stdin.isatty() else {})
text = (data.get("input") or data.get("message") or "").strip()
parts = text.split(None, 2)
action = (parts[0].lower() if parts else "help")
arg = parts[1] if len(parts) > 1 else ""
rest = parts[2] if len(parts) > 2 else ""
token = os.environ.get("GITHUB_TOKEN", "")


def api(method, path, body=None):
    url = "https://api.github.com" + path
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "ideal-agent", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return {"error": e.code, "detail": e.read().decode()[:400]}


if action == "issue" and arg and rest:
    res = api("POST", f"/repos/{arg}/issues", {"title": rest})
    if "error" in res:
        print("error:", res["error"], res.get("detail"))
    else:
        print(f"issue #{res.get('number')}: {res.get('html_url')}")
elif action == "list" and arg:
    res = api("GET", f"/repos/{arg}/issues?state=open&per_page=15")
    if isinstance(res, list):
        for it in res:
            print(f"#{it['number']} {it['title']}")
    else:
        print("error:", res)
elif action == "read" and arg and rest:
    res = api("GET", f"/repos/{arg}/issues/{rest}")
    if "error" in res:
        print("error:", res)
    else:
        print(f"#{res.get('number')} {res.get('title')}\n{res.get('body','')}")
elif action == "repos":
    res = api("GET", "/user/repos?per_page=30")
    if isinstance(res, list):
        for r in res:
            print(r["full_name"])
    else:
        print("error:", res)
else:
    print("usage:")
    print("  issue <owner/repo> <title>")
    print("  list <owner/repo>")
    print("  read <owner/repo> <number>")
    print("  repos")
PY
