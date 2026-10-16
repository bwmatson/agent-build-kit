"""Under `own` a tier 2 unit runs the tests its branch added or changed, selected by
identifier with the marker kept, one command per project that has one; the scope is one
function's decision, taken before the stack lock (spec: tier2-scope)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import ProjectConfig, Tier2UnitScope
from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.e2e import stack_lock
from agent_build_kit.pipeline.wiring import Tier2Run, Tier2Scope, tier2_scope
from agent_build_kit.profiles.python_uv import PROFILE
from tests.tier2_scope_fakes import (
    CHANGED,
    NEW,
    NOTHING,
    OLD,
    PASSED,
    WHOLE,
    Ran,
    branch,
    session,
)

OWN_IDS = ["tests/live/test_new.py::test_new", "tests/live/test_old.py::test_old"]


def adds_one_and_changes_one(tmp_path: Path) -> tuple[Path, str]:
    return branch(
        tmp_path,
        {"tests/live/test_new.py": NEW, "tests/live/test_old.py": CHANGED},
        base_files={"tests/live/test_old.py": OLD, "tests/live/test_other.py": OLD},
    )


def test_a_unit_that_adds_one_test_and_changes_another_runs_exactly_those_two(
    tmp_path: Path,
) -> None:
    repo, base = adds_one_and_changes_one(tmp_path)
    ran = Ran()

    ok, _ = session(tmp_path, ran).run(cwd=repo, base=base)

    assert ok
    [command] = ran.commands
    # The marker and every other option of the whole run stay; only the paths are the ids.
    assert command[: len(WHOLE)] == WHOLE
    assert sorted(command[len(WHOLE) :]) == OWN_IDS
    assert "local_stack" in command


def test_a_changed_test_without_the_marker_is_not_run_and_collecting_nothing_is_no_test(
    tmp_path: Path,
) -> None:
    repo, base = branch(
        tmp_path,
        {"tests/unit/test_old.py": CHANGED},
        base_files={"tests/unit/test_old.py": OLD},
    )
    ran = Ran(NOTHING, code=PROFILE.no_tests_collected_exit)
    gate = session(tmp_path, ran)

    ok, snapshot = gate.run(cwd=repo, base=base)

    # The marker is on the command, so the runner deselects the test; nothing is a failure.
    assert ok
    assert "local_stack" in ran.commands[0]
    assert gate.result is not None
    assert gate.result.ran_no_tests
    assert gate.result.passed == gate.result.failed == 0
    assert "no e2e-test ran" in snapshot


def test_each_projects_command_carries_ids_relative_to_that_project(tmp_path: Path) -> None:
    repo, base = branch(
        tmp_path,
        {"api/tests/live/test_new.py": NEW, "web/tests/live/test_old.py": CHANGED},
        base_files={"api/tests/live/test_x.py": OLD, "web/tests/live/test_old.py": OLD},
    )
    ran = Ran()
    gate = session(tmp_path, ran, projects=[ProjectConfig(path="api"), ProjectConfig(path="web")])

    ok, _ = gate.run(cwd=repo, base=base)

    assert ok
    assert [(c[len(WHOLE) :], where) for c, where in ran.calls] == [
        (["tests/live/test_new.py::test_new"], repo / "api"),
        (["tests/live/test_old.py::test_old"], repo / "web"),
    ]


def test_a_project_with_none_of_the_ids_runs_nothing(tmp_path: Path) -> None:
    repo, base = branch(
        tmp_path,
        {"api/tests/live/test_new.py": NEW},
        base_files={"web/tests/live/test_x.py": OLD},
    )
    ran = Ran()
    gate = session(tmp_path, ran, projects=[ProjectConfig(path="api"), ProjectConfig(path="web")])

    gate.run(cwd=repo, base=base)

    assert [where for _, where in ran.calls] == [repo / "api"]


# --- one decision, taken before the lock ------------------------------------------------


def decide(
    repo: Path, base: str | None, setting: Tier2UnitScope = Tier2UnitScope.OWN
) -> Tier2Scope:
    return tier2_scope(
        repo,
        base,
        change="add-marker",
        setting=setting,
        profile=PROFILE,
        projects=[],
        marker="local_stack",
        dev_stack=None,
    )


def test_the_scope_function_names_own_with_the_identifiers(tmp_path: Path) -> None:
    repo, base = adds_one_and_changes_one(tmp_path)

    scope = decide(repo, base)

    assert scope.mode is Tier2UnitScope.OWN
    assert sorted(scope.ids) == OWN_IDS


def test_the_scope_function_names_full_with_the_reason(tmp_path: Path) -> None:
    repo, base = adds_one_and_changes_one(tmp_path)

    scope = decide(repo, base, Tier2UnitScope.FULL)

    assert scope.mode is Tier2UnitScope.FULL
    assert scope.reason


def test_a_unit_that_changes_no_test_is_own_with_nothing_to_run(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {"src/app.py": "x = 1\n"}, base_files={"tests/t.py": OLD})

    scope = decide(repo, base)

    assert scope.mode is Tier2UnitScope.OWN
    assert scope.ids == []
    assert "no e2e test added or changed" in scope.reason


def test_the_step_asks_the_scope_function_before_the_lock_and_obeys_its_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, base = adds_one_and_changes_one(tmp_path)
    asked: list[tuple[Path, str | None]] = []
    lock_held_when_asked: list[bool] = []
    chosen = "tests/live/test_fake.py::test_fake"
    answer = Tier2Scope(
        mode=Tier2UnitScope.OWN,
        ids=[chosen],
        runs=[Tier2Run(where=repo, commands=[[*WHOLE, chosen]])],
    )
    ran = Ran()
    gate = session(tmp_path, ran)

    def decided(cwd: Path, base: str | None, **kwargs: object) -> Tier2Scope:
        asked.append((cwd, base))
        lock_held_when_asked.append(gate.lock.exists() and bool(gate.lock.read_text()))
        return answer

    monkeypatch.setattr(wiring, "e2e_scope", decided)

    gate.run(cwd=repo, base=base)

    assert asked == [(repo, base)]
    assert lock_held_when_asked == [False]
    # The step ran what it was told, and narrowed nothing itself.
    assert ran.commands == [[*WHOLE, chosen]]


def test_a_second_caller_gets_the_same_answer_as_the_step(tmp_path: Path) -> None:
    repo, base = adds_one_and_changes_one(tmp_path)
    ran = Ran(PASSED)

    session(tmp_path, ran).run(cwd=repo, base=base)

    assert sorted(ran.commands[0][len(WHOLE) :]) == sorted(decide(repo, base).ids)


# --- a workspace repo: each member's command runs from the member's directory -----------


def members(tmp_path: Path, changed: dict[str, str]) -> tuple[Path, str]:
    base_files = {"pyproject.toml": '[tool.uv.workspace]\nmembers = ["svc-a", "svc-b"]\n'}
    for member in ("svc-a", "svc-b"):
        base_files[f"{member}/pyproject.toml"] = f'[project]\nname = "{member}"\n'
        base_files[f"{member}/tests/live/test_old.py"] = OLD
    return branch(tmp_path, changed, base_files=base_files)


def test_a_changed_live_test_of_one_member_runs_only_that_members_command_with_relative_ids(
    tmp_path: Path,
) -> None:
    repo, base = members(tmp_path, {"svc-a/tests/live/test_new.py": NEW})
    ran = Ran()

    ok, _ = session(tmp_path, ran).run(cwd=repo, base=base)

    assert ok
    [command] = ran.commands
    assert command[command.index("--directory") + 1] == "svc-a"
    assert command[-1] == "tests/live/test_new.py::test_new"
    assert "local_stack" in command


def test_a_changed_test_outside_every_member_runs_nothing_and_skips_the_lock(
    tmp_path: Path,
) -> None:
    repo, base = members(tmp_path, {"tests/live/test_root.py": NEW})
    ran = Ran()
    log: list[str] = []
    gate = session(tmp_path, ran, log=log, timeout=0.1)

    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        ok, _ = gate.run(cwd=repo, base=base)

    assert ok
    assert ran.calls == []
    assert "e2e-test skipped: no e2e test added or changed" in log
