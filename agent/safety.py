from __future__ import annotations
import json
import os
import re
import shlex
import sqlite3
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .memory import state_dir


class AuditLog:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(state_dir(), "audit.db")
        # Audit writes may come from HTTP handler threads, not the thread that
        # constructed Agent.
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._lock = threading.RLock()
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS audit("
            "ts REAL, decision TEXT, tool TEXT, args TEXT, result TEXT)"
        )

    def record(self, decision: str, tool: str, args: Any, result: str):
        with self._lock:
            self.conn.execute(
                "INSERT INTO audit VALUES(?,?,?,?,?)",
                (time.time(), decision, tool, json.dumps(args)[:2000], str(result)[:4000]),
            )
            self.conn.commit()

    def recent(self, limit: int = 10):
        limit = max(1, min(int(limit), 50))
        with self._lock:
            rows = self.conn.execute(
                "SELECT ts, decision, tool, result FROM audit ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {"ts": ts, "decision": decision, "tool": tool, "result": result}
            for ts, decision, tool, result in rows
        ]

    def close(self):
        with self._lock:
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


def run_sandboxed(command: str, timeout: int = 30, cwd: Optional[str] = None,
                  mode: str = "required") -> str:
    """Run a shell command under the configured sandbox policy.

    ``required`` rejects execution without a sandbox, ``best-effort`` falls
    back to the host, and ``disabled`` always uses the host. The latter two are
    explicit configuration choices intended only for trusted local development.
    """
    mode = (mode or "required").lower()
    if mode not in ("required", "best-effort", "disabled"):
        return "ошибка: sandbox_mode должен быть required, best-effort или disabled"
    available = _has_bwrap() or _has_unshare()
    sandboxed = mode != "disabled" and available
    if mode == "required" and not available:
        return "ошибка: sandbox shell недоступен; установи bwrap/unshare или выбери sandbox_mode=best-effort"
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
        # Не bind'им `/` целиком: это оставило бы доступным чтение всех файлов
        # хоста. Нужны только runtime-директории для shell и библиотек.
        args = ["bwrap", "--unshare-net", "--die-with-parent", "--new-session"]
        for directory in ("/usr", "/bin", "/lib", "/lib64"):
            # На современных Debian/Ubuntu /bin и /lib обычно symlink в /usr;
            # /usr уже смонтирован, повторный bind в ту же точку не нужен.
            if os.path.exists(directory) and not os.path.islink(directory):
                args.extend(["--ro-bind", directory, directory])
        args.extend(["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                     "--bind", work, work, "--chdir", work, "--"])
        shell = "/usr/bin/sh" if os.path.exists("/usr/bin/sh") else "/bin/sh"
        args.extend([shell, "-c", command])
        return shlex.join(args)
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
