"""A repository declaring a node project beside a Python one is narrowed like any other, and one
whose node profile lacks the repeat hook is still run whole (spec: node-npm-lint-and-test)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import E2eUnitScope, ProjectConfig
from agent_build_kit.pipeline.wiring import E2eScope, e2e_scope
from agent_build_kit.profiles.python_uv import PROFILE
from tests.e2e_scope_fakes import NEW, OLD, Unselecting, branch
from tests.node_workspace import manifest

CANNOT = "cannot select tests by identifier"
SKIPPED = "e2e-test skipped"
WEB_E2E = "web/src/a.local_stack.test.ts"


def decide(tmp_path: Path, changed: dict[str, str] | None = None) -> tuple[Path, E2eScope]:
    repo, base = branch(
        tmp_path,
        changed or {"api/tests/live/test_new.py": NEW},
        base_files={"api/tests/live/test_old.py": OLD, WEB_E2E: ""},
    )
    manifest(repo / "web", "web")
    scope = e2e_scope(
        repo,
        base,
        change="add-marker",
        setting=E2eUnitScope.OWN,
        profile=PROFILE,
        projects=[ProjectConfig(path="api"), ProjectConfig(path="web", profile="node-npm")],
        marker="local_stack",
        dev_stack=None,
    )
    return repo, scope


def test_a_repository_is_narrowed_only_while_every_profile_in_it_has_the_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, scope = decide(tmp_path / "with")

    # The node profile repeats tests, so the Python-only unit lists only the Python run.
    assert scope.mode is E2eUnitScope.OWN
    assert [run.where for run in scope.runs] == [repo / "api"]
    assert CANNOT not in scope.reason

    real = profiles.get
    monkeypatch.setattr(
        profiles, "get", lambda name: Unselecting(real(name)) if name == "node-npm" else real(name)
    )
    _, whole = decide(tmp_path / "without")

    # A profile that lacks the hook still runs the repository whole.
    assert whole.mode is E2eUnitScope.FULL
    assert CANNOT in whole.reason
    assert "plain-profile" in whole.reason


def test_a_unit_that_changed_only_a_node_e2e_test_runs_it_in_the_node_project(
    tmp_path: Path,
) -> None:
    repo, scope = decide(tmp_path, {WEB_E2E: "// changed\n"})

    assert scope.mode is E2eUnitScope.OWN
    assert SKIPPED not in scope.reason
    assert [run.where for run in scope.runs] == [repo / "web"]
    [command] = scope.runs[0].commands
    assert command[5:] == ["src/a.local_stack.test.ts"]
    assert WEB_E2E in scope.ids


def test_a_unit_that_changed_a_node_test_that_is_not_e2e_runs_nothing_and_says_why(
    tmp_path: Path,
) -> None:
    _, scope = decide(tmp_path, {"web/src/b.test.ts": "// new\n"})

    assert scope.mode is E2eUnitScope.OWN
    assert scope.runs == []
    assert SKIPPED in scope.reason
