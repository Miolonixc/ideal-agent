import json
import os
import re
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from .memory import state_dir


class AuditLog:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(state_dir(), "audit.db")
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS audit("
            "ts REAL, decision TEXT, tool TEXT, args TEXT, result TEXT)"
        )

    def record(self, decision: str, tool: str, args: Any, result: str):
        self.conn.execute(
            "INSERT INTO audit VALUES(?,?,?,?,?)",
            (time.time(), decision, tool, json.dumps(args)[:2000], str(result)[:4000]),
        )
        self.conn.commit()


class ApprovalGate:
    def __init__(self, mode: str = "auto", allow: Optional[List[str]] = None,
                 deny: Optional[List[str]] = None):
        self.mode = mode
        self.allow = allow or []
        self.deny = deny or []

    def _match(self, pattern: str, tool: str, args: Any) -> bool:
        if ":" in pattern:
            t, rest = pattern.split(":", 1)
            if t != "*" and t != tool:
                return False
            text = args if isinstance(args, str) else json.dumps(args)
            return True if rest == "*" else re.search(rest, text) is not None
        return pattern == tool

    def decide(self, tool: str, args: Any) -> Tuple[str, Optional[str]]:
        for d in self.deny:
            if self._match(d, tool, args):
                return "deny", f"запрещено правилом: {d}"
        if self.mode == "full-auto":
            return "allow", None
        if self.mode == "suggest":
            return "ask", None
        for a in self.allow:
            if self._match(a, tool, args):
                return "allow", None
        if tool in ("read_file", "glob", "grep"):
            return "allow", None
        return "ask", None


def run_sandboxed(command: str, timeout: int = 30) -> str:
    wrapped = _sandbox_command(command) if os.environ.get("IDEAL_SANDBOX") else command
    try:
        r = subprocess.run(
            wrapped, shell=True, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return "error: timeout"
    out = r.stdout
    if r.returncode != 0:
        out += "\n[stderr]\n" + r.stderr
    return out[:8000] or "(пусто)"


def _sandbox_command(command: str) -> str:
    if _has_bwrap():
        return (
            "bwrap --ro-bind / / --dev /dev --tmpfs /tmp "
            "--unshare-net " + command
        )
    if _has_unshare():
        return f"unshare -r {command}"
    return command


def _has_unshare() -> bool:
    try:
        subprocess.run(["unshare", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _has_bwrap() -> bool:
    try:
        subprocess.run(["bwrap", "--version"], capture_output=True, check=True)
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def make_diff(old: str, new: str, path: str = "") -> str:
    import difflib
    diff = difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    )
    return "\n".join(diff)
