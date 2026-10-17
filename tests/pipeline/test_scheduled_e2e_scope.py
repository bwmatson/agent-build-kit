"""The scope function decides on its own that a scheduled change runs the whole suite, so any
caller, the open-fix gate included, gets the same answer (spec: e2e-schedule)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import E2eUnitScope
from agent_build_kit.pipeline.wiring import e2e_scope
from agent_build_kit.profiles.python_uv import PROFILE
from tests.scheduled_e2e_fakes import CHANGE, default_branch


def test_a_scheduled_change_is_full_under_own_with_the_reason(tmp_path: Path) -> None:
    repo, base = default_branch(tmp_path / "repo")

    scope = e2e_scope(
        repo,
        base,
        change=CHANGE,
        setting=E2eUnitScope.OWN,
        profile=PROFILE,
        projects=[],
        marker="local_stack",
        dev_stack=None,
    )

    assert scope.mode is E2eUnitScope.FULL
    assert scope.reason == "e2e-test runs whole: a scheduled run is the whole suite"
    assert scope.runs
