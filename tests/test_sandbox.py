from __future__ import annotations
import os
import unittest
from unittest import mock

from agent import safety


class TestSandbox(unittest.TestCase):
    def test_sandbox_command_prefers_bwrap(self):
        with mock.patch("agent.safety._has_bwrap", return_value=True), \
             mock.patch("agent.safety._has_unshare", return_value=True):
            os.environ["IDEAL_SANDBOX"] = "1"
            self.assertIn("bwrap", safety._sandbox_command("ls"))
            del os.environ["IDEAL_SANDBOX"]

    def test_sandbox_command_falls_to_unshare(self):
        with mock.patch("agent.safety._has_bwrap", return_value=False), \
             mock.patch("agent.safety._has_unshare", return_value=True):
            os.environ["IDEAL_SANDBOX"] = "1"
            self.assertTrue(safety._sandbox_command("ls").startswith("unshare"))
            del os.environ["IDEAL_SANDBOX"]

    def test_run_sandboxed_calls_wrapped(self):
        os.environ["IDEAL_SANDBOX"] = "1"
        captured = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            class R:
                stdout = "ok"
                stderr = ""
                returncode = 0
            return R()

        with mock.patch("agent.safety.subprocess.run", fake_run), \
             mock.patch("agent.safety._has_unshare", return_value=True), \
             mock.patch("agent.safety._has_bwrap", return_value=False):
            out = safety.run_sandboxed("echo hi")
        del os.environ["IDEAL_SANDBOX"]
        self.assertTrue(captured["cmd"].startswith("unshare"))
        self.assertEqual(out, "ok")


if __name__ == "__main__":
    unittest.main()
