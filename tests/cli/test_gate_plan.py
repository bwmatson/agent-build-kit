"""`abk gate` takes the unit's groups from the `Unit:` trailer of the branch's commits, so a
test-only group's lone `test:` commit is accepted, and with no plan it is refused
(spec: a-test-only-group-commits-no-pair)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import profiles, runtimes
from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import gate
from agent_build_kit.pipeline.stack_runner import change_dir_of
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.factories import commit_files, git, init_repo, unit
from tests.runner_fakes import approving
from tests.runtimes.stand_in import StandInRuntime
from tests.stub_gate_support import ModeProfile

TASKS = """# Tasks

Acceptance: none — a fixture about test-only groups

## 1. [app] [unit-test] Cover it

- [ ] 1.1 Test: it.
- [ ] 1.2 Do it.

## 2. [app] [e2e-test] Drive it

- [ ] 2.1 Test: it runs.
"""


def trailer(title: str, *, unit_id: str = "feature/1") -> str:
    return f"{title}\n\nUnit: {unit_id}\n" if unit_id else title


def installation_with_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    setting: bool = True,
    unit_id: str = "feature/1",
) -> Installation:
    """An installation whose `app` checkout is on a unit branch of a lone group-1 pair and a
    lone group-2 tests commit, the commits carrying `unit_id` as their trailer ("" for none)."""
    inst = make_installation(tmp_path / "planning", builders={"stubbed_tdd_commits": setting})
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    change = change_dir_of(inst.root, "feature")
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(TASKS)
    UnitStore(inst.state_dir / "units.json").upsert(
        [unit("feature/1", change="feature", groups=(1, 2))]
    )
    app = init_repo(inst.root / "checkouts" / "app")
    commit_files(app, "base", {"README.md": "base\n"})
    git(app, "checkout", "-q", "-b", "spec/feature/1")
    commit_files(
        app,
        trailer("test: Cover it", unit_id=unit_id),
        {"tests/test_a.py": "def test_a(): assert False\n"},
    )
    commit_files(app, trailer("feat: Cover it", unit_id=unit_id), {"src/a.py": "x = 1\n"})
    commit_files(
        app,
        trailer("test: Drive it", unit_id=unit_id),
        {"tests/test_drive.py": "def test_d(): assert False\n"},
    )
    monkeypatch.setattr(runtimes, "active", lambda: StandInRuntime(answer=approving()))
    monkeypatch.setattr(profiles, "get", lambda name: ModeProfile())
    return inst


def gate_in(inst: Installation, monkeypatch: pytest.MonkeyPatch, *, cwd: Path | None = None) -> int:
    monkeypatch.chdir(cwd or inst.root)
    return main(["gate", "--repo", str(inst.root / "checkouts" / "app"), "--base", "main"])


def record_checks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """`check_branch` recording the keyword arguments it is asked with, and finding nothing."""
    asked: list[dict[str, Any]] = []

    def record(repo: Path, base: str, **kwargs: Any) -> list[str]:
        asked.append(kwargs)
        return []

    monkeypatch.setattr(gate, "check_branch", record)
    return asked


def test_the_lone_tests_commit_of_an_e2e_group_is_accepted_through_the_trailers_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation_with_branch(tmp_path, monkeypatch)

    assert gate_in(inst, monkeypatch) == 0, capsys.readouterr().out


def test_the_same_branch_with_no_trailer_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = installation_with_branch(tmp_path, monkeypatch, unit_id="")

    assert gate_in(inst, monkeypatch) == 1
    assert "test: Drive it" in capsys.readouterr().out


def test_the_same_branch_outside_an_installation_is_given_no_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation_with_branch(tmp_path, monkeypatch)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    asked = record_checks(monkeypatch)

    gate_in(inst, monkeypatch, cwd=elsewhere)

    assert [call["groups"] for call in asked] == [()]


def test_with_the_setting_off_the_gate_is_given_no_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = installation_with_branch(tmp_path, monkeypatch, setting=False)
    asked = record_checks(monkeypatch)

    assert gate_in(inst, monkeypatch) == 0

    assert [call["groups"] for call in asked] == [()]
    assert [call["stubbed"] for call in asked] == [False]
