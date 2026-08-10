from __future__ import annotations
import json
import os
import re
import shlex
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

    def close(self):
        self.conn.close()


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


def run_sandboxed(command: str, timeout: int = 30, cwd: Optional[str] = None) -> str:
    """Run a command only in an available OS sandbox.

    Set IDEAL_ALLOW_UNSANDBOXED_SHELL=1 only for trusted local development.
    """
    sandboxed = os.environ.get("IDEAL_SANDBOX", "1") != "0"
    if sandboxed and not (_has_bwrap() or _has_unshare()):
        return "ошибка: sandbox shell недоступен; установи bwrap или явно задай IDEAL_ALLOW_UNSANDBOXED_SHELL=1"
    if not sandboxed and os.environ.get("IDEAL_ALLOW_UNSANDBOXED_SHELL") != "1":
        return "ошибка: запуск без sandbox запрещён; задай IDEAL_ALLOW_UNSANDBOXED_SHELL=1 только в доверенной среде"
    wrapped = _sandbox_command(command, cwd) if sandboxed else command
    try:
        r = subprocess.run(
            wrapped, shell=True, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
    except subprocess.TimeoutExpired:
        return "ошибка: таймаут"
    out = r.stdout
    if r.returncode != 0:
        out += "\n[stderr]\n" + r.stderr
    return out[:8000] or "(пусто)"


def _sandbox_command(command: str, cwd: Optional[str] = None) -> str:
    if _has_bwrap():
        work = os.path.realpath(cwd) if cwd else "/tmp"
        return (
            "bwrap --ro-bind / / --bind " + work + " " + work +
            " --chdir " + work + " --dev /dev --tmpfs /tmp --unshare-net --die-with-parent -- /bin/sh -c " +
            shlex.quote(command)
        )
    if _has_unshare():
        return "unshare -r --net -- /bin/sh -c " + shlex.quote(command)
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
