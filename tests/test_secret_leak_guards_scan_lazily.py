"""Importing `tests/test_secret_leak_guards.py` reads no repository file for its scan.

A scan at import runs for every collection, marked or not, so marking the tests that need it
would remove nothing.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.tracked_files import ROOT

GUARDS = ROOT / "tests" / "test_secret_leak_guards.py"


def test_importing_the_guard_module_reads_no_test_file(monkeypatch: pytest.MonkeyPatch) -> None:
    read: list[Path] = []
    real = Path.read_text

    def recording(self: Path, *args, **kwargs):
        read.append(self)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", recording)
    spec = importlib.util.spec_from_file_location("secret_leak_guards_fresh_import", GUARDS)
    assert spec is not None and spec.loader is not None

    spec.loader.exec_module(importlib.util.module_from_spec(spec))

    assert [str(path) for path in read if ROOT / "tests" in path.parents] == []
