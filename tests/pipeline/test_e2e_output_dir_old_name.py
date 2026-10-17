"""The output directory left under the old name is moved to the current one on first use."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_build_kit.compat_names import old_spelling
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.run_log import e2e_output_dir

OLD_DIR = f"{old_spelling(TestTier.E2E_TEST)}-output"


def test_a_directory_under_the_old_name_alone_is_moved_with_a_notice(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / OLD_DIR).mkdir()
    (tmp_path / OLD_DIR / "a.log").write_text("kept")

    with caplog.at_level(logging.WARNING):
        found = e2e_output_dir(tmp_path)

    assert found == tmp_path / "e2e-output"
    assert (found / "a.log").read_text() == "kept"
    assert not (tmp_path / OLD_DIR).exists()
    assert OLD_DIR in caplog.text


def test_neither_directory_is_touched_when_both_exist(tmp_path: Path) -> None:
    (tmp_path / OLD_DIR).mkdir()
    (tmp_path / OLD_DIR / "old.log").write_text("old")
    (tmp_path / "e2e-output").mkdir()
    (tmp_path / "e2e-output" / "new.log").write_text("new")

    found = e2e_output_dir(tmp_path)

    assert [p.name for p in found.iterdir()] == ["new.log"]
    assert [p.name for p in (tmp_path / OLD_DIR).iterdir()] == ["old.log"]
