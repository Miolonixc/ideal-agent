from __future__ import annotations

import os
import subprocess
import unittest


class TestInstaller(unittest.TestCase):
    def test_shell_syntax(self):
        root = os.path.dirname(os.path.dirname(__file__))
        script = os.path.join(root, "install.sh")
        self.assertEqual(subprocess.run(["bash", "-n", script]).returncode, 0)

    def test_help_is_side_effect_free(self):
        root = os.path.dirname(os.path.dirname(__file__))
        out = subprocess.run(
            ["bash", "install.sh", "--help"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("--service", out)
        self.assertIn("IDEAL_LLM_API_KEY", out)

    def test_update_script_syntax_and_help(self):
        root = os.path.dirname(os.path.dirname(__file__))
        script = os.path.join(root, "update.sh")
        self.assertEqual(subprocess.run(["bash", "-n", script]).returncode, 0)
        out = subprocess.run(
            ["bash", "update.sh", "--help"], cwd=root,
            capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("--check", out)
        self.assertIn("--no-restart", out)


if __name__ == "__main__":
    unittest.main()
