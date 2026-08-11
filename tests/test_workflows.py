from __future__ import annotations

import os
import unittest


class TestWorkflows(unittest.TestCase):
    def test_android_artifact_has_checksum(self):
        path = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "android.yml")
        with open(path, encoding="utf-8") as f:
            workflow = f.read()
        self.assertIn("Create APK checksum", workflow)
        self.assertIn("sha256sum *.apk", workflow)
        self.assertIn("*.sha256", workflow)

