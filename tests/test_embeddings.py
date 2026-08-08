import json
import unittest
from unittest import mock

from agent.embeddings import HashEmbedder, RemoteEmbedder, build_embedder
from agent.config import AgentConfig


class TestEmbeddings(unittest.TestCase):
    def test_hash_normalized(self):
        v = HashEmbedder(dim=64)("привет мир привет")
        self.assertEqual(len(v), 64)
        self.assertAlmostEqual(sum(x * x for x in v), 1.0, places=5)

    def test_build_hash(self):
        cfg = AgentConfig(embeddings={"provider": "hash", "dim": 32})
        emb = build_embedder(cfg)
        self.assertIsNotNone(emb)
        self.assertEqual(len(emb("x")), 32)

    def test_remote(self):
        cfg = AgentConfig(embeddings={"provider": "remote", "model": "m",
                                      "api_key": "k", "base_url": "https://x/v1"})
        with mock.patch("urllib.request.urlopen") as u:
            u.return_value.__enter__.return_value.read.return_value = json.dumps(
                {"data": [{"embedding": [0.1, 0.2, 0.3]}]}).encode()
            emb = build_embedder(cfg)
            self.assertEqual(emb("hi"), [0.1, 0.2, 0.3])


if __name__ == "__main__":
    unittest.main()
