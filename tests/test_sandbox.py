from __future__ import annotations
import unittest
from unittest import mock

from agent import safety


class TestSandbox(unittest.TestCase):
    def test_sandbox_command_prefers_bwrap(self):
        with mock.patch("agent.safety._has_bwrap", return_value=True), \
             mock.patch("agent.safety._has_unshare", return_value=True):
            self.assertIn("bwrap", safety._sandbox_command("ls"))

    def test_sandbox_command_falls_to_unshare(self):
        with mock.patch("agent.safety._has_bwrap", return_value=False), \
             mock.patch("agent.safety._has_unshare", return_value=True):
            self.assertTrue(safety._sandbox_command("ls").startswith("unshare"))

    def test_run_sandboxed_calls_wrapped(self):
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
            out = safety.run_sandboxed("echo hi", mode="required")
        self.assertTrue(captured["cmd"].startswith("unshare"))
        self.assertEqual(out, "ok")

    def test_required_rejects_missing_sandbox(self):
        with mock.patch("agent.safety._has_unshare", return_value=False), \
             mock.patch("agent.safety._has_bwrap", return_value=False):
            self.assertIn("недоступен", safety.run_sandboxed("echo hi", mode="required"))

    def test_best_effort_uses_host_without_sandbox(self):
        captured = {}

        def fake_run(cmd, *a, **k):
            captured["cmd"] = cmd
            class R:
                stdout = "ok"
                stderr = ""
                returncode = 0
            return R()

        with mock.patch("agent.safety.subprocess.run", fake_run), \
             mock.patch("agent.safety._has_unshare", return_value=False), \
             mock.patch("agent.safety._has_bwrap", return_value=False):
            self.assertEqual(safety.run_sandboxed("echo hi", mode="best-effort"), "ok")
        self.assertEqual(captured["cmd"], "echo hi")


if __name__ == "__main__":
    unittest.main()
