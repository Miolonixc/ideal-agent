#!/bin/sh
python3 - "$@" <<'PY'
import sys, json, os
raw = os.environ.get("IDEAL_SKILL_INPUT")
data = json.loads(raw) if raw else (json.load(sys.stdin) if not sys.stdin.isatty() else {})
root = data.get("path", os.getcwd())
out = []
for dp, dirs, fs in os.walk(root):
    if any(x in dp for x in ("/.git", "/node_modules", "/__pycache__", "/.venv")):
        continue
    for fn in fs:
        out.append(os.path.join(dp, fn))
print("\n".join(out[:200]))
PY
