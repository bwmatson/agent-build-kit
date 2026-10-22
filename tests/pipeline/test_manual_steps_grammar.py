"""The `Manual:` grammar, `abk tags` on it, and a step reaching the unit (spec: manual-steps)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planner import parse_graph
from agent_build_kit.pipeline.units import ManualStep
from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks

OPT_OUT = "\nAcceptance: none — a fixture about another rule\n"
RUNBOOK = "docs/runbook-feature.md"
STEP = f"Manual: flip-marker — Flip the marker in abk.yaml — runbook: {RUNBOOK}#flip"


def parse(text: str, tmp_path: Path) -> tuple[list[TaskGroup], list[ValidationError]]:
    (tmp_path / "tasks.md").write_text(text + OPT_OUT)
    return validate_tasks(tmp_path / "tasks.md")


def group_with(*lines: str) -> str:
    return "## 1. [app] [unit-test] A\n" + "".join(f"{line}\n" for line in lines) + "- [ ] 1.1 x\n"


def test_a_manual_line_gives_the_group_a_step_with_its_runbook(tmp_path: Path) -> None:
    groups, errors = parse(group_with(STEP), tmp_path)

    assert errors == []
    assert [
        (step.slug, step.text, step.runbook, step.check) for step in groups[0].manual_steps
    ] == [("flip-marker", "Flip the marker in abk.yaml", f"{RUNBOOK}#flip", "")]


def test_a_check_line_is_the_check_of_the_step_before_it(tmp_path: Path) -> None:
    groups, errors = parse(group_with(STEP, "Check: grep -q on abk.yaml"), tmp_path)

    assert errors == []
    assert groups[0].manual_steps[0].check == "grep -q on abk.yaml"


def test_a_duplicate_slug_in_a_change_is_rejected(tmp_path: Path) -> None:
    text = group_with(STEP) + "\n## 2. [app] [unit-test] B\n" + STEP + "\n- [ ] 2.1 y\n"

    _, errors = parse(text, tmp_path)

    assert len(errors) == 1
    assert "flip-marker" in errors[0].message


def test_an_empty_description_is_rejected(tmp_path: Path) -> None:
    line = f"Manual: flip-marker —  — runbook: {RUNBOOK}#flip"

    _, errors = parse(group_with(line), tmp_path)

    assert len(errors) == 1
    assert "Manual" in errors[0].message
    assert errors[0].line == 2


def write_change(installation: Installation, tasks: str, runbook: str | None) -> None:
    path = installation.changes_dir / "feature" / "tasks.md"
    path.parent.mkdir(parents=True)
    path.write_text("# Tasks\n" + OPT_OUT + "\n" + tasks)
    if runbook is not None:
        (installation.root / RUNBOOK).parent.mkdir(parents=True, exist_ok=True)
        (installation.root / RUNBOOK).write_text(runbook)


def tags_output(installation: Installation, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    status = cli.cmd_tags(build_parser().parse_args(["tags", "feature"]), installation)
    return status, capsys.readouterr().out


def test_a_missing_runbook_file_is_a_warning_and_not_a_problem(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_change(installation, group_with(STEP), runbook=None)

    status, out = tags_output(installation, capsys)

    assert status == 0
    assert "warning" in out
    assert RUNBOOK in out


def test_a_missing_runbook_heading_is_a_warning(
    installation: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    write_change(installation, group_with(STEP), runbook="# Runbook\n\n## other\n")

    status, out = tags_output(installation, capsys)

    assert status == 0
    assert "warning" in out
    assert "flip" in out


def test_the_planner_carries_a_groups_steps_to_the_unit_that_holds_it() -> None:
    step = ManualStep(slug="flip-marker", text="Flip it", runbook=f"{RUNBOOK}#flip")
    group = TaskGroup(
        number=1,
        repo="app",
        tier="unit-test",
        title="A",
        line=3,
        task_count=1,
        manual_steps=(step,),
    )
    reply = json.dumps(
        {
            "units": [
                {
                    "id": "feature/1",
                    "change": "feature",
                    "title": "t",
                    "repo": "app",
                    "tier": "unit-test",
                    "groups": [1],
                }
            ]
        }
    )

    units = parse_graph(reply, groups=[group], tasks="## 1. [app] [unit-test] A\n- [ ] 1.1 x\n")

    assert units[0].manual_steps == (step,)
