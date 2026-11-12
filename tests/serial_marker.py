"""Test support: the guard that keeps a `serial` marker out of the tests and configuration.

A test that cannot run beside others is isolated, not marked. The guard reads the tracked test
and configuration files and names each one that holds the word, except the guard's own files and
the changelog.
"""

from pathlib import Path

# The word the guard keeps out. A test that needs it as data (a command still carrying the old
# selection) takes it from here, so the word stays in this file.
MARKER = "serial"


def serial_marker_problems(root: Path) -> list[str]:
    """One line per tracked test or configuration file below `root` that names `serial`."""
    raise NotImplementedError
