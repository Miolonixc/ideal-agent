from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest


class TestSbom(unittest.TestCase):
    def test_android_sbom_is_cyclonedx_and_contains_app(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        gradle = os.path.join(root, "android", "idealagent", "app", "build.gradle.kts")
        script = os.path.join(root, "tools", "generate_android_sbom.py")
        with tempfile.TemporaryDirectory() as directory:
            output = os.path.join(directory, "app.sbom.json")
            subprocess.run([sys.executable, script, "--gradle", gradle, "--output", output], check=True)
            with open(output, encoding="utf-8") as f:
                sbom = json.load(f)
        self.assertEqual(sbom["bomFormat"], "CycloneDX")
        self.assertEqual(sbom["metadata"]["component"]["version"], "0.2.7")
        self.assertTrue(any(c["name"] == "activity-compose" for c in sbom["components"]))

