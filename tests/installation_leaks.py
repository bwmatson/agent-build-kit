"""The structural leak scan, over a checkout's text and its committed planning content.

`tests/test_no_installation_leaks.py` runs it over this repository; tests of the scan
itself run it over a temporary tree.
"""

from __future__ import annotations

from pathlib import Path


def leaks(root: Path) -> list[str]:
    """Each hit under `root` as `path:line: clipped line`: home paths, non-fixture slugs,
    anecdotes and product directories in the scanned text, planning content included."""
    raise NotImplementedError


def repo_path_leaks(root: Path) -> list[str]:
    """One finding per `repos.<name>.path` of `root`'s committed `abk.yaml` that leaves the
    checkout, naming the repo key and never the value."""
    raise NotImplementedError
