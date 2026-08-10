#!/bin/sh
python3 - "$@" <<'PY'
import sys, json, subprocess, os
raw = os.environ.get("IDEAL_SKILL_INPUT")
data = json.loads(raw) if raw else (json.load(sys.stdin) if not sys.stdin.isatty() else {})
path = data.get("path", os.getcwd())
r = subprocess.run(["python3", "-m", "pytest", "-q"], cwd=path,
                   capture_output=True, text=True)
if r.returncode != 0 and not r.stdout and not r.stderr:
    r = subprocess.run(["python3", "-m", "unittest", "discover", "-s", path],
                       cwd=path, capture_output=True, text=True)
out = (r.stdout or r.stderr)
print(out[:3000])
PY
