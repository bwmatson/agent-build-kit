"""The prompts name the reports directory with `__REPORTS_DIR__`; the earlier `__STATE_DIR__` is
still filled, with the reports directory (spec: track-reports-dir)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.tracks import runner
from tests.tracks.test_prompts import TOP_LEVEL
from tests.tracks.test_runner import described_installation, project


@pytest.mark.parametrize("path", TOP_LEVEL, ids=lambda p: p.stem)
def test_the_packaged_prompts_name_the_reports_directory_and_not_the_state_directory(
    path: Path,
) -> None:
    text = path.read_text()

    assert "__REPORTS_DIR__" in text
    assert "__STATE_DIR__" not in text


def test_a_prompt_with_the_old_token_renders_it_as_the_reports_directory(tmp_path: Path) -> None:
    custom = tmp_path / "prompts"
    custom.mkdir()
    (custom / "health.md").write_text("logs go in __STATE_DIR__ and also __REPORTS_DIR__\n")
    state = tmp_path / "state"
    inst = described_installation(
        tmp_path / "planning",
        tracks={"prompts_dir": str(custom)},
        planning=dict(state_dir=str(state)),
    )

    rendered = runner.render_prompt(inst, project(inst), "health")

    reports = inst.root / "docs" / "reports"
    assert rendered == f"logs go in {reports} and also {reports}\n"
    assert str(state) not in rendered
