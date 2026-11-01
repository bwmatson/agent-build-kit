"""`abk tags --fix-projects` writes the project a group resolved to into its heading, and
`abk tags` and `abk check` warn of a change that mixes tagged and resolved groups
(spec: project-resolution)."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.units import MERGED
from tests.cli.replan_driver import Replan
from tests.cli.tags_fix_support import line_about, run_tags, write_change
from tests.factories import new_unit
from tests.project_workspace import repos_declaring, tasks_editing

RESOLVED = ("[app] [unit-test] Add it", "web/src/a.ts")
STAYS = ("[app] [unit-test] Stay", "CHANGELOG.md")
WRITTEN = ("[app/web] [unit-test] Written", "web/src/b.ts")


def planning_with_web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Replan:
    return Replan(
        tmp_path, monkeypatch, repos=repos_declaring(tmp_path / "planning", "app", ("web",))
    )


def test_fix_projects_rewrites_only_the_repo_part_of_the_heading_and_keeps_every_other_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    original = tasks_editing(RESOLVED, STAYS).replace("\n", "\r\n").rstrip("\r\n").encode()
    path = write_change(run, "feature", original)

    code, out = run_tags(capsys, "--fix-projects", "feature")

    assert code == 0, out
    assert path.read_bytes() == original.replace(b"## 1. [app] ", b"## 1. [app/web] ", 1)


def test_fix_and_fix_projects_together_are_a_usage_error_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    original = tasks_editing(RESOLVED).encode()
    path = write_change(run, "feature", original)

    code, out = run_tags(capsys, "--fix", "--fix-projects", "feature")

    assert code == 2
    assert "--fix-projects" in out
    assert path.read_bytes() == original


def test_fix_projects_with_all_tags_the_groups_of_every_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    original = tasks_editing(RESOLVED).encode()
    paths = [write_change(run, name, original) for name in ("alpha", "beta")]

    code, out = run_tags(capsys, "--fix-projects", "--all")

    assert code == 0, out
    for path in paths:
        assert path.read_bytes() == original.replace(b"## 1. [app] ", b"## 1. [app/web] ", 1)


def test_fix_projects_lists_the_groups_that_stayed_in_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    write_change(run, "feature", tasks_editing(RESOLVED, STAYS, WRITTEN).encode())

    code, out = run_tags(capsys, "--fix-projects", "feature")

    assert code == 0, out
    assert "Stay" in line_about(out, "Stay") and "root" in line_about(out, "Stay")
    assert "Add it" not in out


def test_fix_projects_dry_run_says_what_it_would_tag_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    original = tasks_editing(RESOLVED, STAYS).encode()
    path = write_change(run, "feature", original)

    code, out = run_tags(capsys, "--fix-projects", "--dry-run", "feature")

    assert code == 0, out
    assert "would tag 1 group(s)" in out
    assert path.read_bytes() == original


def test_fix_projects_skips_a_group_whose_unit_has_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    original = tasks_editing(RESOLVED, ("[app] [unit-test] Later", "web/src/c.ts")).encode()
    path = write_change(run, "feature", original)
    run.store.import_units(
        [new_unit("feature/1", groups=(1,), state=MERGED, branch="spec/feature/1", pr=1)]
    )

    code, out = run_tags(capsys, "--fix-projects", "feature")

    assert code == 0, out
    assert path.read_bytes() == original.replace(b"## 2. [app] ", b"## 2. [app/web] ", 1)


def test_fix_projects_does_not_rehash_the_plan_so_the_unstarted_units_are_re_planned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    write_change(run, "feature", tasks_editing(RESOLVED).encode())
    run.record("feature")
    recorded = run.records["feature"]["hash"]

    code, out = run_tags(capsys, "--fix-projects", "feature")

    assert code == 0, out
    assert run.records["feature"]["hash"] == recorded
    assert cli.plan_digest(run.inst.changes_dir / "feature" / "tasks.md", inst=run.inst) != recorded


def test_fix_projects_refuses_a_change_with_another_tag_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    original = tasks_editing(RESOLVED, ("[nowhere] [unit-test] Lost", "web/src/c.ts")).encode()
    path = write_change(run, "feature", original)

    code, out = run_tags(capsys, "--fix-projects", "feature")

    assert code == 1
    assert "refused" in out and "nowhere" in out
    assert path.read_bytes() == original


def test_fix_projects_refuses_a_file_that_is_not_valid_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    broken = b"\xff\xfe" + tasks_editing(RESOLVED).encode()
    path = write_change(run, "feature", broken)

    code, out = run_tags(capsys, "--fix-projects", "feature")

    assert code == 1
    assert "not valid text" in line_about(out, "feature")
    assert path.read_bytes() == broken


def test_fix_projects_refuses_a_needs_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    first = tasks_editing(RESOLVED).replace(
        "\n- [ ] 1.1", "\nNeeds: second group 1 — a reason\n\n- [ ] 1.1", 1
    )
    second = tasks_editing(RESOLVED).replace(
        "\n- [ ] 1.1", "\nNeeds: first group 1 — a reason\n\n- [ ] 1.1", 1
    )
    path = write_change(run, "first", first.encode())
    write_change(run, "second", second.encode())

    code, out = run_tags(capsys, "--fix-projects", "first")

    assert code == 1, out
    assert "refused" in out
    assert path.read_text() == first


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only file")
def test_fix_projects_refuses_a_read_only_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    original = tasks_editing(RESOLVED).encode()
    path = write_change(run, "feature", original)
    path.chmod(0o444)

    code, out = run_tags(capsys, "--fix-projects", "feature")

    assert code == 1
    assert "read-only" in line_about(out, "feature")
    assert path.read_bytes() == original


def test_tags_warns_of_a_change_that_mixes_a_written_project_and_a_resolved_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning_with_web(tmp_path, monkeypatch)
    write_change(run, "feature", tasks_editing(RESOLVED, WRITTEN).encode())

    code, out = run_tags(capsys, "feature")

    warning = next(line for line in out.splitlines() if "mix" in line)
    assert code == 0, out
    assert "--fix-projects" in warning

    write_change(run, "feature", tasks_editing(RESOLVED, STAYS).encode())
    _, consistent = run_tags(capsys, "feature")
    assert "mix" not in consistent


def test_check_warns_of_a_change_that_mixes_a_written_project_and_a_resolved_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from agent_build_kit import openspec

    monkeypatch.setattr(openspec, "check", lambda root: (True, ""))
    run = planning_with_web(tmp_path, monkeypatch)
    write_change(run, "feature", tasks_editing(RESOLVED, WRITTEN).encode())

    capsys.readouterr()
    code = cli.cmd_check(argparse.Namespace(), run.inst)

    out = capsys.readouterr().out
    warning = next(line for line in out.splitlines() if "mix" in line)
    assert code == 0, out
    assert "--fix-projects" in warning
