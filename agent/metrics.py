"""Optional, local-only aggregate metrics.

The database deliberately contains event names and counters only. Do not add
prompts, replies, attachment names, tool arguments, credentials, session IDs,
timestamps or network identifiers here.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Dict, Optional

from .memory import state_dir


class MetricsStore:
    """Thread-safe counters for an explicitly enabled local installation."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(state_dir(), "metrics.db")
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS counters (event TEXT PRIMARY KEY, count INTEGER NOT NULL)"
        )
        self.conn.commit()

    def record(self, event: str) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO counters(event, count) VALUES(?, 1) "
                "ON CONFLICT(event) DO UPDATE SET count = count + 1",
                (event,),
            )
            self.conn.commit()

    def summary(self) -> Dict[str, int]:
        with self._lock:
            rows = self.conn.execute("SELECT event, count FROM counters ORDER BY event").fetchall()
        return {str(event): int(count) for event, count in rows}

    def close(self) -> None:
        self.conn.close()
