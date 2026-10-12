"""The run log and `abk status` name the file holding a failed tier 2 run's output."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as pipeline_cli
from agent_build_kit.pipeline.run_log import tier2_output_dir
from agent_build_kit.pipeline.unit_store import FeedbackSource, UnitStore
from agent_build_kit.pipeline.units import FAILED
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.tier2_failure_fakes import run_failing_tier2

NAME = "feature-01-20261011-120000-1.log"


def _snapshot(path: Path) -> str:
    filler = "\n".join(f"output line {n}" for n in range(200))
    return f"## Tier 2 results\n- **Full output:** `{path}`\n<details>\n{filler}\n</details>\n"


def test_the_run_log_has_a_line_with_the_path_even_when_the_tail_cut_leaves_it_out(
    tmp_path: Path,
) -> None:
    path = tier2_output_dir(tmp_path / "state") / NAME

    _, logs = run_failing_tier2(tmp_path, _snapshot(path))

    (log,) = logs.iterdir()
    assert any(str(path) in line for line in log.read_text().splitlines())


def test_status_shows_the_file_of_a_unit_whose_last_result_was_a_tier_2_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tier2_output_dir(tmp_path)
    directory.mkdir()
    shown = directory / NAME
    other = directory / "alone-01-20261011-120000-1.log"
    for file in (shown, other):
        file.write_text("whole output\n")

    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("feature/1", state=FAILED), new_unit("alone/1", state=FAILED)])
    # An upsert keeps what a run saved, never what the unit was built with.
    store.set_feedback(
        "feature/1", f"tier 2 failed:\n{_snapshot(shown)}", source=FeedbackSource.TIER2
    )
    store.set_feedback("alone/1", "tier 1 failed:\nlint", source=FeedbackSource.TIER1)
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)

    assert pipeline_cli.cmd_status(argparse.Namespace(), workspace) == 0

    lines = capsys.readouterr().out.splitlines()
    assert any(NAME in line and "feature/1" in line for line in lines)
    assert not any(other.name in line for line in lines)


def _status_of(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    feedback: str,
    source: FeedbackSource,
) -> list[str]:
    workspace = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([new_unit("feature/1", state=FAILED)])
    store.set_feedback("feature/1", feedback, source=source)
    monkeypatch.setattr(pipeline_cli, "current_usage", lambda: None)
    assert pipeline_cli.cmd_status(argparse.Namespace(), workspace) == 0
    return capsys.readouterr().out.splitlines()


def test_status_names_the_latest_file_when_feedback_holds_two_tier_2_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first = tier2_output_dir(tmp_path) / "feature-01-20261011-110000-tier2.log"
    second = tier2_output_dir(tmp_path) / "feature-01-20261011-120000-tier2.log"
    feedback = f"tier 2 failed:\n{_snapshot(first)}\n\ntier 2 failed:\n{_snapshot(second)}"

    lines = _status_of(tmp_path, monkeypatch, capsys, feedback, FeedbackSource.TIER2)

    assert any(second.name in line for line in lines)
    assert not any(first.name in line for line in lines)


def test_status_names_the_file_when_a_persons_review_feedback_came_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    file = tier2_output_dir(tmp_path) / NAME
    feedback = f"please rename it\n\ntier 2 failed:\n{_snapshot(file)}"

    lines = _status_of(tmp_path, monkeypatch, capsys, feedback, FeedbackSource.REVIEW)

    assert any(NAME in line and "feature/1" in line for line in lines)
