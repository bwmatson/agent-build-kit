"""Whether a test that runs the node profile's commands for real can run here."""

from __future__ import annotations

import functools
import subprocess

import pytest

# A `node` that has not answered by then is looking for a toolchain on the network.
START_DEADLINE = 10


@functools.cache
def node_starts() -> bool:
    """Whether `node` starts here within the deadline; asked once for the whole run."""
    try:
        return (
            subprocess.run(["node", "-v"], capture_output=True, timeout=START_DEADLINE).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        return False


def require_node() -> None:
    """Skip the test unless `node` starts: the profile's script probe reads the manifest with
    it, as `npm run` itself needs it."""
    if not node_starts():
        pytest.skip("node does not start on this machine")
