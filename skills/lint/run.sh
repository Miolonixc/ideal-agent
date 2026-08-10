#!/bin/sh
python3 - "$@" <<'PY'
import sys, json, subprocess, os

raw = os.environ.get("IDEAL_SKILL_INPUT")
data = json.loads(raw) if raw else (json.load(sys.stdin) if not sys.stdin.isatty() else {})
path = (data.get("input") or data.get("message") or "").strip()
if not path:
    print("usage: lint <path.py>")
    sys.exit(0)
if not os.path.isfile(path):
    print(f"error: файл не найден: {path}")
    sys.exit(0)
r = subprocess.run([sys.executable, "-m", "py_compile", path],
                   capture_output=True, text=True)
if r.returncode == 0:
    print(f"OK: {path} компилируется без ошибок")
else:
    print(r.stderr[:3000])
PY
