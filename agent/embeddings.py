import json
import math
import os
import re
import urllib.request
from typing import List, Optional


class HashEmbedder:
    def __init__(self, dim: int = 256):
        self.dim = dim

    def __call__(self, text: str) -> List[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"\w+", (text or "").lower()):
            v[hash(tok) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]


class RemoteEmbedder:
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def __call__(self, text: str) -> List[float]:
        body = json.dumps({"model": self.model, "input": text}).encode()
        req = urllib.request.Request(
            self.base_url + "/embeddings",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        return data["data"][0]["embedding"]


def build_embedder(cfg) -> Optional[callable]:
    e = getattr(cfg, "embeddings", None)
    if not e:
        return None
    provider = e.get("provider", "hash")
    if provider == "hash":
        return HashEmbedder(dim=int(e.get("dim", 256)))
    if provider == "remote":
        key = e.get("api_key") or os.environ.get("EMBED_API_KEY") or ""
        return RemoteEmbedder(
            e.get("base_url", "https://api.tokenrouter.com/v1"),
            key,
            e.get("model", "text-embedding-3-small"),
        )
    return None
