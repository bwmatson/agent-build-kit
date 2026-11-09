"""Whether a test that runs the node profile's commands for real can run here."""

from __future__ import annotations

import subprocess

import pytest


def require_node() -> None:
    """Skip the test unless `node` starts: the profile's script probe reads the manifest with
    it, as `npm run` itself needs it."""
    try:
        started = subprocess.run(["node", "-v"], capture_output=True).returncode == 0
    except OSError:
        started = False
    if not started:
        pytest.skip("node does not start on this machine")
