import os
import sys
import urllib.error
import urllib.request

import json

def _cfg_token():
    p = os.path.expanduser("~/.config/ideal-agent/config.json")
    if os.path.exists(p):
        try:
            return json.load(open(p, encoding="utf-8")).get("telegram", {}).get("token")
        except Exception:
            return None
    return None

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or _cfg_token()
if not TOKEN:
    print("нет TELEGRAM_BOT_TOKEN (и нет telegram.token в config.json)")
    sys.exit(1)
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "77002359")
path = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/dev/ideal-agent/install.sh")

with open(path, "rb") as f:
    data = f.read()

boundary = "----idealagentboundary"
body = (
    b"--" + boundary.encode() + b"\r\n"
    b'Content-Disposition: form-data; name="chat_id"\r\n\r\n' + CHAT.encode() + b"\r\n"
    + b"--" + boundary.encode() + b"\r\n"
    + b'Content-Disposition: form-data; name="document"; filename="'
    + os.path.basename(path).encode() + b'"\r\n'
    + b"Content-Type: application/octet-stream\r\n\r\n"
    + data + b"\r\n"
    + b"--" + boundary.encode() + b"--\r\n"
)
req = urllib.request.Request(
    f"https://api.telegram.org/bot{TOKEN}/sendDocument",
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print(r.read().decode())
except urllib.error.URLError as e:
    print("ошибка сети:", e)
