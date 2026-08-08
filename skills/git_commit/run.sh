#!/bin/sh
python3 - "$@" <<'PY'
import sys, json, subprocess
raw = os.environ.get("IDEAL_SKILL_INPUT")
data = json.loads(raw) if raw else (json.load(sys.stdin) if not sys.stdin.isatty() else {})
msg = data.get("message", "update")
subprocess.run(["git", "add", "-A"], capture_output=True, text=True)
r = subprocess.run(["git", "commit", "-m", msg], capture_output=True, text=True)
print((r.stdout or r.stderr)[:2000])
PY
