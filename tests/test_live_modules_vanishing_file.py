"""The scan for live-stack modules gives the same answer whatever else touches `tests/` while it
runs: a file listed and gone by the time it is read is not a module, and not an error."""

from __future__ import annotations

from pathlib import Path

from tests.live_tag_drift import find_live_modules

LIVE = "import pytest\n\npytestmark = pytest.mark.local_stack\n\n\ndef test_x():\n    pass\n"


def test_a_file_listed_and_gone_before_it_is_read_is_skipped(tmp_path: Path) -> None:
    live = tmp_path / "tests" / "integration" / "test_live.py"
    live.parent.mkdir(parents=True)
    live.write_text(LIVE)
    # A link to a file that was removed: the directory still lists it, reading it fails, which
    # is what another test deleting a file during the scan looks like, with no clock involved.
    (tmp_path / "tests" / "test_vanished.py").symlink_to(tmp_path / "removed.py")

    assert find_live_modules(tmp_path / "tests") == [live]
