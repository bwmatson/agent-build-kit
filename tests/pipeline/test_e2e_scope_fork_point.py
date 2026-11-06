"""The e2e-test scope names the tests the unit's branch changed since it left its base, whatever
the base has gained since (spec: unit-own-tests)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import E2eUnitScope
from agent_build_kit.pipeline.wiring import E2eScope, e2e_scope
from agent_build_kit.profiles.python_uv import PROFILE
from tests.e2e_scope_fakes import CHANGED, NEW, OLD, Ran, session
from tests.factories import commit_files, git, init_repo

OWN_IDS = ["tests/live/test_new.py::test_new", "tests/live/test_old.py::test_old"]
SKIPPED = "e2e-test skipped: no e2e test added or changed"


def moved_on(tmp_path: Path, *, adds: bool = True) -> Path:
    """A unit that left `main` at A; `main` has since moved to B, which changed a test the
    unit's checkout also has. The unit's branch is checked out."""
    repo = init_repo(tmp_path / "repo")
    commit_files(
        repo,
        "A",
        {
            "pyproject.toml": "[project]\nname = 'app'\n",
            "tests/live/test_old.py": OLD,
            "tests/live/test_shared.py": OLD,
        },
    )
    git(repo, "switch", "-q", "-c", "unit")
    if adds:
        commit_files(
            repo, "unit", {"tests/live/test_new.py": NEW, "tests/live/test_old.py": CHANGED}
        )
    git(repo, "switch", "-q", "main")
    commit_files(repo, "B", {"tests/live/test_shared.py": CHANGED})
    git(repo, "switch", "-q", "unit")
    return repo


def decide(repo: Path, base: str | None, setting: E2eUnitScope = E2eUnitScope.OWN) -> E2eScope:
    return e2e_scope(
        repo,
        base,
        change="add-marker",
        setting=setting,
        profile=PROFILE,
        projects=[],
        marker="local_stack",
        dev_stack=None,
    )


def test_a_unit_whose_base_moved_on_without_a_restack_names_only_its_own_tests(
    tmp_path: Path,
) -> None:
    repo = moved_on(tmp_path)

    scope = decide(repo, "main")

    assert scope.mode is E2eUnitScope.OWN
    assert sorted(scope.ids) == OWN_IDS


def test_the_same_unit_after_a_restack_names_the_tests_it_carries_on_the_new_base(
    tmp_path: Path,
) -> None:
    repo = moved_on(tmp_path)
    git(repo, "rebase", "-q", "main")

    scope = decide(repo, "main")

    assert sorted(scope.ids) == OWN_IDS
    assert "tests/live/test_shared.py::test_old" not in scope.ids


def test_the_session_runs_only_the_units_tests_against_a_base_that_moved_on(
    tmp_path: Path,
) -> None:
    repo = moved_on(tmp_path)
    ran = Ran()

    ok, _ = session(tmp_path, ran).run(cwd=repo, base="main")

    assert ok
    [command] = ran.commands
    assert sorted(command[-2:]) == OWN_IDS


def test_the_full_setting_still_runs_whole(tmp_path: Path) -> None:
    repo = moved_on(tmp_path)

    scope = decide(repo, "main", E2eUnitScope.FULL)

    assert scope.mode is E2eUnitScope.FULL
    assert scope.reason == "e2e-test runs whole: e2e_unit_scope is full"


def test_a_unit_with_no_test_added_or_changed_skips_whatever_the_base_gained(
    tmp_path: Path,
) -> None:
    repo = moved_on(tmp_path, adds=False)
    ran, log = Ran(), []

    ok, _ = session(tmp_path, ran, log=log).run(cwd=repo, base="main")

    assert ok
    assert ran.commands == []
    assert SKIPPED in log
    assert decide(repo, "main").runs == []
