from __future__ import annotations

import json
import os
import unittest


class TestOpenTUI(unittest.TestCase):
    def test_opentui_client_is_pinned_and_uses_local_stream_api(self):
        root = os.path.join(os.path.dirname(__file__), "..", "opentui")
        with open(os.path.join(root, "package.json"), encoding="utf-8") as f:
            package = json.load(f)
        self.assertEqual(package["dependencies"]["@opentui/core"], "0.4.5")
        self.assertEqual(package["devDependencies"]["typescript"], "5.7.3")
        self.assertEqual(package["devDependencies"]["@types/node"], "22.15.3")
        with open(os.path.join(root, "src", "index.ts"), encoding="utf-8") as f:
            source = f.read()
        self.assertIn("/message/stream", source)
        self.assertIn("X-Ideal-Agent-Token", source)
        self.assertIn("ScrollBoxRenderable", source)
        self.assertIn('key.name === "f3"', source)
        self.assertIn("/sessions/${encodeURIComponent(config.sessionId)}/cancel", source)
        self.assertIn('text.startsWith("/attach ")', source)
        self.assertIn("attachments: sentAttachments", source)
        self.assertIn("MAX_ATTACHMENT_BYTES", source)
        self.assertNotIn("api_key", source.lower())

    def test_opentui_has_a_bun_typecheck_workflow(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        with open(os.path.join(root, ".github", "workflows", "opentui.yml"), encoding="utf-8") as f:
            workflow = f.read()
        self.assertIn("oven-sh/setup-bun", workflow)
        self.assertIn("bun run check", workflow)
