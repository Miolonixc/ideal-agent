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
        self.assertIn("actions/cache@v4", workflow)
        self.assertIn("for attempt in 1 2 3", workflow)

    def test_android_release_requires_signing_secrets(self):
        path = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "android-release.yml")
        with open(path, encoding="utf-8") as f:
            workflow = f.read()
        self.assertIn("ANDROID_KEYSTORE_BASE64", workflow)
        self.assertIn("assembleRelease", workflow)
        self.assertIn("action-gh-release", workflow)
        self.assertIn("GITHUB_REF_NAME", workflow)
        self.assertIn("IDEAL_APP_VERSION_NAME", workflow)
        self.assertIn("actions/cache@v4", workflow)
        self.assertIn("for attempt in 1 2 3", workflow)
