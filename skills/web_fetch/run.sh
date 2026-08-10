#!/bin/sh
python3 - "$@" <<'PY'
import sys, json, re, urllib.request, urllib.error

raw = os.environ.get("IDEAL_SKILL_INPUT")
data = json.loads(raw) if raw else (json.load(sys.stdin) if not sys.stdin.isatty() else {})
url = (data.get("input") or data.get("message") or "").strip()
if not url:
    print("usage: web_fetch <url>")
    sys.exit(0)

try:
    req = urllib.request.Request(url, headers={"User-Agent": "ideal-agent/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        raw = r.read()
    enc = r.headers.get_content_charset() or "utf-8"
    html = raw.decode(enc, errors="replace")
except Exception as e:
    print(f"error: {e}")
    sys.exit(0)

# убираем скрипты/стили
html = re.sub(r"(?is)<(script|style|head|noscript).*?</\1>", " ", html)
html = re.sub(r"(?is)<!--.*?-->", " ", html)
text = re.sub(r"(?is)<[^>]+>", " ", html)
text = re.sub(r"&nbsp;", " ", text)
text = re.sub(r"&amp;", "&", text)
text = re.sub(r"&lt;", "<", text)
text = re.sub(r"&gt;", ">", text)
text = re.sub(r"[ \t]+", " ", text)
text = re.sub(r"\n\s*\n+", "\n", text)
print(text.strip()[:8000])
PY
