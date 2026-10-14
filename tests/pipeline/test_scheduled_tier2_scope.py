"""The scope function decides on its own that a scheduled change runs the whole suite, so any
caller, the open-fix gate included, gets the same answer (spec: tier2-schedule)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import Tier2UnitScope
from agent_build_kit.pipeline.wiring import tier2_scope
from agent_build_kit.profiles.python_uv import PROFILE
from tests.scheduled_tier2_fakes import CHANGE, default_branch


def test_a_scheduled_change_is_full_under_own_with_the_reason(tmp_path: Path) -> None:
    repo, base = default_branch(tmp_path / "repo")

    scope = tier2_scope(
        repo,
        base,
        change=CHANGE,
        setting=Tier2UnitScope.OWN,
        profile=PROFILE,
        projects=[],
        marker="local_stack",
        dev_stack=None,
    )

    assert scope.mode is Tier2UnitScope.FULL
    assert scope.reason == "tier 2 runs whole: a scheduled run is the whole suite"
    assert scope.runs
