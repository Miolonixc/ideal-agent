from __future__ import annotations
import os
import shutil
import tempfile
import unittest

from agent.safety import run_sandboxed


@unittest.skipUnless(shutil.which("bwrap"), "requires bubblewrap")
class TestSandboxIntegration(unittest.TestCase):
    def test_bwrap_isolates_host_and_allows_workspace_write(self):
        with tempfile.TemporaryDirectory() as workspace:
            result = run_sandboxed(
                "echo safe > created.txt && test -f created.txt && test ! -e /etc/passwd && ! grep -qE 'eth0|ens|wlan' /proc/net/dev",
                cwd=workspace, mode="required",
            )
            self.assertNotIn("[stderr]", result)
            with open(os.path.join(workspace, "created.txt"), encoding="utf-8") as f:
                self.assertEqual(f.read().strip(), "safe")
