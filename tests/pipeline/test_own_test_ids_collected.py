"""The own-test selection of an e2e-test unit names a touched test only when the profile's
runner collects its file, so a helper module or `conftest.py` is never named (spec: e2e-scope)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import E2eUnitScope
from agent_build_kit.pipeline.e2e import stack_lock
from agent_build_kit.pipeline.wiring import E2eScope, e2e_scope
from agent_build_kit.profiles.python_uv import PROFILE
from tests.e2e_scope_fakes import NEW, Ran, branch, session

SKIPPED = "e2e-test skipped: no e2e test added or changed"
HELPER = "tests/integration/replay_unit_build.py"
DRIVER = "tests/integration/test_replay.py"
HELPER_TEST = "def test_the_unit_is_built():\n    assert True\n"
DRIVER_TEST = "def test_driver():\n    assert True\n"


def decide(repo: Path, base: str) -> E2eScope:
    return e2e_scope(
        repo,
        base,
        change="add-marker",
        setting=E2eUnitScope.OWN,
        profile=PROFILE,
        projects=[],
        marker="local_stack",
        dev_stack=None,
    )


def named(tmp_path: Path, path: str) -> list[str]:
    repo, base = branch(tmp_path, {path: NEW})
    return decide(repo, base).ids


def test_a_helper_module_with_a_test_function_is_named_neither_in_ids_nor_in_the_command(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {HELPER: HELPER_TEST, DRIVER: DRIVER_TEST})
    ran = Ran()

    scope = decide(repo, base)
    session(tmp_path, ran).run(cwd=repo, base=base)

    assert scope.ids == [f"{DRIVER}::test_driver"]
    [command] = ran.commands
    assert f"{DRIVER}::test_driver" in command
    assert not [arg for arg in command if "replay_unit_build" in arg]


@pytest.mark.parametrize(
    "path",
    [
        "tests/integration/test_replay.py",
        "tests/integration/replay_test.py",
        "pkg/test_replay.py",
    ],
)
def test_a_test_or_underscore_test_module_is_named_wherever_it_is(
    tmp_path: Path, path: str
) -> None:
    assert PROFILE.collects_path(path)
    assert named(tmp_path, path) == [f"{path}::test_new"]


@pytest.mark.parametrize(
    "path", ["tests/integration/conftest.py", "tests/pkg/tests/helpers.py", "tests/helpers.py"]
)
def test_conftest_and_a_helper_in_a_nested_tests_folder_are_not_named(
    tmp_path: Path, path: str
) -> None:
    assert named(tmp_path, path) == []


@pytest.mark.parametrize("path", ["tests/conftest.py", "tests/helpers.py"])
def test_the_profile_collects_test_and_underscore_test_modules_and_not_helpers(
    path: str,
) -> None:
    assert PROFILE.collects_path("test_x.py")
    assert PROFILE.collects_path("x_test.py")
    assert not PROFILE.collects_path(path)
    assert PROFILE.is_test_path(path)


@pytest.mark.parametrize("path", ["src/a.test.ts", "src/__tests__/b.ts", "src/c.ts"])
def test_the_node_profile_collects_what_it_calls_a_test_path(path: str) -> None:
    profile = profiles.get("node-npm")

    assert profile.collects_path(path) == profile.is_test_path(path)
    assert profile.collects_path(path) == (path != "src/c.ts")


def test_a_unit_that_touched_only_a_helper_selects_nothing_takes_no_lock_and_says_which(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {HELPER: HELPER_TEST})
    ran = Ran()
    log: list[str] = []
    gate = session(tmp_path, ran, log=log, timeout=0.1)

    scope = decide(repo, base)
    with stack_lock(gate.lock, timeout=1, holder="another/1"):
        ok, _ = gate.run(cwd=repo, base=base)

    assert (scope.runs, scope.ids) == ([], [])
    assert scope.reason.startswith(SKIPPED)
    assert HELPER in scope.reason
    assert "not collected" in scope.reason
    assert ok
    assert ran.calls == []
    [line] = [line for line in log if line.startswith(SKIPPED)]
    assert HELPER in line
    assert gate.result is not None
    assert gate.result.ran_no_tests


def test_a_unit_that_touched_no_test_has_the_reason_with_nothing_appended(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {"src/app.py": "x = 1\n"})

    scope = decide(repo, base)

    assert scope.reason == SKIPPED


def test_a_helper_beside_a_driver_leaves_no_skip_reason_when_a_run_remains(
    tmp_path: Path,
) -> None:
    repo, base = branch(tmp_path, {HELPER: HELPER_TEST, DRIVER: DRIVER_TEST})

    assert decide(repo, base).reason == ""


def test_a_test_named_method_in_a_source_file_is_not_listed_as_a_left_out_test(
    tmp_path: Path,
) -> None:
    source = "class Client:\n    def test_connection(self):\n        return True\n"
    repo, base = branch(tmp_path, {"src/app.py": source})

    assert decide(repo, base).reason == SKIPPED
