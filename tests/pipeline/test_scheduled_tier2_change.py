"""The change a round writes for a due repo is fixed text with one tier 2 group, no spec, no
model and no git (spec: tier2-schedule)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tier2_schedule import scheduled_name, write_due
from agent_build_kit.pipeline.work_graph import old_test_kind_warnings, validate_tasks
from tests.tier2_schedule_fakes import TODAY, planning, store_of


def written_change(tmp_path: Path, repo: str = "app") -> tuple[Installation, Path]:
    inst = planning(tmp_path, {repo: None})
    [name] = write_due(inst, store_of(inst, repo), today=TODAY, say=lambda line: None)
    assert name == scheduled_name(repo, TODAY)
    return inst, inst.changes_dir / name


def test_the_change_has_a_proposal_a_design_and_tasks_and_no_spec(tmp_path: Path) -> None:
    _, change = written_change(tmp_path)

    assert sorted(p.name for p in change.iterdir()) == [
        ".openspec.yaml",
        "design.md",
        "proposal.md",
        "tasks.md",
    ]
    assert (change / ".openspec.yaml").read_text() == "schema: spec-driven\nskip_specs: true\n"
    assert not (change / "specs").exists()
    proposal = (change / "proposal.md").read_text()
    for heading in ("## Why", "## What Changes", "## Impact"):
        assert heading in proposal
    assert "app" in proposal and TODAY.isoformat() in proposal
    assert (change / "design.md").read_text().strip()


def test_tasks_say_acceptance_none_with_a_reason(tmp_path: Path) -> None:
    _, change = written_change(tmp_path)

    [line] = [
        line for line in (change / "tasks.md").read_text().splitlines() if "Acceptance:" in line
    ]
    assert line.startswith("Acceptance: none")
    assert line.removeprefix("Acceptance: none").strip(" —-:"), "the reason follows"


def test_tasks_hold_one_tier_2_group_of_the_repo_with_priority_3_and_separate(
    tmp_path: Path,
) -> None:
    inst, change = written_change(tmp_path)

    groups, errors = validate_tasks(change / "tasks.md", repos=tuple(inst.repos))

    assert errors == []
    [group] = groups
    assert (group.number, group.repo, group.tier) == (1, "app", "e2e-test")
    assert group.priority == 3
    assert old_test_kind_warnings(change / "tasks.md") == []
    assert group.separate
    assert group.task_count == 1
    assert "full tier 2 suite" in group.title.lower()
    assert "default branch" in group.title.lower()
    text = (change / "tasks.md").read_text()
    assert any(line.startswith("Separate:") for line in text.splitlines())
    assert text.count("- [ ] 1.1 ") == 1 and "- [x]" not in text


def test_the_group_names_the_repo_it_is_written_for(tmp_path: Path) -> None:
    inst = planning(tmp_path, {"app": None, "platform": None})
    store = store_of(inst, "app", "platform")

    names = write_due(inst, store, today=TODAY, say=lambda line: None)

    assert sorted(names) == [scheduled_name("app", TODAY), scheduled_name("platform", TODAY)]
    for repo in ("app", "platform"):
        tasks = inst.changes_dir / scheduled_name(repo, TODAY) / "tasks.md"
        groups, _ = validate_tasks(tasks, repos=tuple(inst.repos))
        assert [g.repo for g in groups] == [repo]


def test_writing_it_calls_no_model_and_no_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"a process was started: {args!r}")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)

    assert write_due(inst, store, today=TODAY, say=lambda line: None) == [
        scheduled_name("app", TODAY)
    ]


def test_the_change_passes_abk_tags(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    inst, change = written_change(tmp_path)

    assert cli.cmd_tags(argparse.Namespace(all=False, change=change.name), inst) == 0

    assert "1 task group(s), all tagged" in capsys.readouterr().out
