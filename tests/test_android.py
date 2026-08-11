from __future__ import annotations

import os
import re
import unittest


ROOT = os.path.join(os.path.dirname(__file__), "..", "android", "idealagent")


class TestAndroidCompanion(unittest.TestCase):
    def test_version_is_installable_upgrade_and_visible_in_settings(self):
        with open(os.path.join(ROOT, "app", "build.gradle.kts"), encoding="utf-8") as f:
            gradle = f.read()
        code = int(re.search(r"versionCode\s*=\s*(\d+)", gradle).group(1))
        name = re.search(r'versionName\s*=\s*"([^"]+)"', gradle).group(1)
        self.assertGreaterEqual(code, 9)
        self.assertEqual(name, "0.2.7")
        self.assertIn("buildConfig = true", gradle)
        with open(os.path.join(ROOT, "app", "src", "main", "java", "com", "idealagent", "MainActivity.kt"), encoding="utf-8") as f:
            activity = f.read()
        self.assertIn("Версия приложения: ${BuildConfig.VERSION_NAME}", activity)
        self.assertIn("class StreamCancellation", activity)
        self.assertIn("onClick = { if (busy) cancelStreaming() else send() }", activity)
        self.assertIn("enum class ConnectionState", activity)
        self.assertIn("Состояние: $stateText", activity)
        self.assertIn("Проверить подключение", activity)
