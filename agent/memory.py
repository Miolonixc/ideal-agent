from __future__ import annotations
import json
import hashlib
import math
import os
import re
import sqlite3
import time
from collections import Counter
from typing import Any, Dict, List, Optional


_TOKEN = re.compile(r"\w+", re.UNICODE)
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".hg",
             ".mypy_cache", ".pytest_cache", "dist", "build", ".cargo"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".gz", ".so",
            ".o", ".exe", ".db", ".pyc", ".bin", ".ico"}


def state_dir() -> str:
    d = os.path.expanduser("~/.local/state/ideal-agent")
    os.makedirs(d, exist_ok=True)
    return d


def workspace_namespace(workspace: str) -> str:
    """Стабильный, нераскрывающий путь идентификатор проекта."""
    canonical = os.path.realpath(os.path.abspath(os.path.expanduser(workspace)))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def workspace_db_path(kind: str, workspace: str) -> str:
    return os.path.join(state_dir(), f"{kind}-{workspace_namespace(workspace)}.db")


def tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


def cosine(a: List[float], b: List[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.records: List[Dict[str, Any]] = []
        self.df: Dict[str, int] = {}
        self.postings: Dict[str, List[int]] = {}
        self.tf: List[Counter] = []
        self.doc_len: List[int] = []
        self.avgdl = 0.0

    def add(self, doc_id: str, text: str, meta: Optional[dict] = None):
        toks = tokenize(text)
        idx = len(self.records)
        self.records.append({"id": doc_id, "text": text, "meta": meta})
        self.doc_len.append(len(toks))
        cnt = Counter(toks)
        self.tf.append(cnt)
        seen = set()
        for t in cnt:
            if t not in self.postings:
                self.postings[t] = []
            self.postings[t].append(idx)
            if t not in seen:
                self.df[t] = self.df.get(t, 0) + 1
                seen.add(t)
        self.avgdl = sum(self.doc_len) / max(1, len(self.doc_len))

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        q = tokenize(query)
        n = len(self.records)
        scores = [0.0] * len(self.records)
        for term in q:
            if term not in self.postings:
                continue
            idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
            for idx in self.postings[term]:
                f = self.tf[idx].get(term, 0)
                dl = self.doc_len[idx]
                denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[idx] += idf * (f * (self.k1 + 1)) / denom
        ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        out = []
        for i in ranked[:top_k]:
            if scores[i] <= 0:
                break
            out.append({
                "id": self.records[i]["id"],
                "score": scores[i],
                "text": self.records[i]["text"],
                "meta": self.records[i]["meta"],
            })
        return out


class RepoIndex:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(state_dir(), "repo_index.db")
        # HTTPChannel handles every request in its own thread. Agent serializes
        # operations with its run lock, so sharing this connection is safe once
        # SQLite's default same-thread guard is disabled.
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS chunks(path TEXT, start INTEGER, text TEXT, embedding TEXT)"
        )
        self.bm25 = BM25Index()
        self.embedder: Optional[Any] = None
        self._chunks: List[Dict[str, Any]] = []

    def set_embedder(self, fn):
        self.embedder = fn

    def build(self, root: str, max_bytes: int = 200000):
        self.conn.execute("DELETE FROM chunks")
        step = 50
        overlap = 10
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for fn in files:
                if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, encoding="utf-8") as f:
                        text = f.read()
                except (OSError, UnicodeDecodeError):
                    continue
                if len(text) > max_bytes:
                    text = text[:max_bytes]
                self._index_file(p, text, step, overlap)
        self.conn.commit()
        self._load()

    def _index_file(self, path: str, text: str, step: int, overlap: int):
        lines = text.splitlines()
        if not lines:
            return
        for i in range(0, len(lines), step - overlap):
            chunk = "\n".join(lines[i:i + step])
            if not chunk.strip():
                continue
            emb = json.dumps(self.embedder(chunk)) if self.embedder else None
            self.conn.execute(
                "INSERT INTO chunks VALUES(?,?,?,?)", (path, i, chunk, emb)
            )

    def _load(self):
        self._chunks = []
        self.bm25 = BM25Index()
        for path, start, text, emb in self.conn.execute(
            "SELECT path, start, text, embedding FROM chunks"
        ):
            emb_obj = json.loads(emb) if emb else None
            self._chunks.append(
                {"path": path, "start": start, "text": text, "embedding": emb_obj}
            )
            self.bm25.add(f"{path}:{start}", text, {"path": path, "start": start})

    def _chunk_by_id(self, cid: str) -> Optional[Dict[str, Any]]:
        for c in self._chunks:
            if f"{c['path']}:{c['start']}" == cid:
                return c
        return None

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        if self.embedder:
            qv = self.embedder(query)
            cands = self.bm25.search(query, top_k=top_k * 3)
            scored = []
            for c in cands:
                rec = self._chunk_by_id(c["id"])
                sim = cosine(qv, rec["embedding"]) if rec and rec["embedding"] else 0.0
                scored.append((c["score"] + sim * 5.0, c))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [c for _, c in scored[:top_k]]
        return self.bm25.search(query, top_k)

    def close(self):
        self.conn.close()


class MemoryStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(state_dir(), "memory.db")
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS memory(scope TEXT, key TEXT, value TEXT, created REAL, used REAL)"
        )
        self.bm25 = BM25Index()
        self._reload()

    def _reload(self):
        self.bm25 = BM25Index()
        for scope, key, value in self.conn.execute(
            "SELECT scope, key, value FROM memory"
        ):
            self.bm25.add(key, value, {"scope": scope, "key": key})

    def add(self, scope: str, key: str, value: str):
        now = time.time()
        self.conn.execute(
            "INSERT OR REPLACE INTO memory VALUES(?,?,?,?,?)",
            (scope, key, value, now, now),
        )
        self.conn.commit()
        self._reload()

    def recall(self, query: str, scope: Optional[str] = None, top_k: int = 5) -> List[Dict[str, Any]]:
        res = self.bm25.search(query, top_k=top_k * 3)
        out = []
        for r in res:
            if scope and r["meta"].get("scope") != scope:
                continue
            out.append(r)
            if len(out) >= top_k:
                break
        return out

    def recent(self, scope: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Return recent local memories without sending them to a provider."""
        limit = max(1, min(int(limit), 20))
        if scope:
            rows = self.conn.execute(
                "SELECT scope, key, value FROM memory WHERE scope=? ORDER BY used DESC LIMIT ?",
                (scope, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT scope, key, value FROM memory ORDER BY used DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {"text": value, "meta": {"scope": item_scope, "key": key}}
            for item_scope, key, value in rows
        ]

    def extract_facts(self, text: str, provider) -> List[str]:
        prompt = (
            "Извлеки факты, решения и предпочтения из текста. "
            "Верни ТОЛЬКО JSON-массив строк, без пояснений."
        )
        resp = provider.complete(
            [{"role": "system", "content": prompt}, {"role": "user", "content": text}],
            stream=False,
        )
        data = resp if isinstance(resp, str) else resp["choices"][0]["message"]["content"]
        facts = _parse_json_list(data)
        for f in facts:
            self.add("auto", f, f)
        return facts

    def close(self):
        self.conn.close()


def _parse_json_list(data: str) -> List[str]:
    start = data.find("[")
    end = data.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        obj = json.loads(data[start:end + 1])
    except json.JSONDecodeError:
        return []
    return [str(x) for x in obj if isinstance(x, (str, int, float))]
