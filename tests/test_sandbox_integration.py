from __future__ import annotations
import os
import shutil
import subprocess
import tempfile
import unittest

from agent.safety import run_sandboxed


def _bwrap_network_namespace_is_usable():
    """GitHub runners can have bwrap installed but deny network namespaces."""
    if not shutil.which("bwrap"):
        return False
    probe = subprocess.run(
        ["bwrap", "--unshare-net", "--die-with-parent", "--new-session", "--", "/bin/sh", "-c", "true"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return probe.returncode == 0


@unittest.skipUnless(_bwrap_network_namespace_is_usable(), "requires usable Bubblewrap network namespace")
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
