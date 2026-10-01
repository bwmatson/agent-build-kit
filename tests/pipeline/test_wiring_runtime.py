"""The build and review runs reach their agent through the runtime seam.

Given a runtime that is not Claude Code, each run is asked for in abk's own
terms — a worktree, the specs it may read, a tool policy, a model already
resolved for its role — and nothing it sends can be a `claude` flag.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import models
from agent_build_kit.pipeline.wiring import (
    REVIEW_PROMPT,
    REVIEW_TOOLS,
    build_run_claude,
    build_run_review,
)
from agent_build_kit.runtimes import ToolPolicy
from tests.conftest import make_installation
from tests.runtimes.stand_in import StandInRuntime


def test_a_build_asks_the_runtime_for_a_policed_run_in_the_worktree(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    make_installation(planning, git={"branch_prefix": "unit/"})
    specs = planning / "openspec"
    tree = tmp_path / "tree"
    runtime = StandInRuntime(answer="built it")

    answer = build_run_claude(runtime=runtime, planning_repo=planning, allowed_tools="Read Edit")(
        "Implement it.", cwd=tree
    )

    assert answer == "built it"
    request = runtime.request
    assert request.prompt == "Implement it."
    assert request.cwd == tree
    assert request.add_dirs == (specs,)
    assert request.policy == ToolPolicy(specs_dir=specs, branch_prefix="unit/")
    assert request.permission_mode == "edit"
    assert request.allowed_tools == "Read Edit"
    assert request.model == models().implement
    assert request.role == "implement"
    assert request.on_event is not None


def test_a_rework_is_asked_for_as_a_rework(tmp_path: Path) -> None:
    runtime = StandInRuntime()

    build_run_claude(runtime=runtime, model=models().rework, role="rework")("Fix it.", cwd=tmp_path)

    assert runtime.request.role == "rework"
    assert runtime.request.model == models().rework


def test_a_failed_build_raises_what_the_runtime_said(tmp_path: Path) -> None:
    """Half-finished edits are on disk: carrying on would commit them."""
    runtime = StandInRuntime(ok=False, error="the turn ended early")

    with pytest.raises(RuntimeError, match="^the turn ended early$"):
        build_run_claude(runtime=runtime)("Implement it.", cwd=tmp_path)


def test_a_review_asks_the_runtime_for_a_read_only_judgement(tmp_path: Path) -> None:
    runtime = StandInRuntime(answer='{"approved": true}')

    answer = build_run_review(runtime=runtime)(cwd=tmp_path)

    assert answer == '{"approved": true}'
    request = runtime.request
    assert request.prompt == REVIEW_PROMPT
    assert request.cwd == tmp_path
    assert request.allowed_tools == REVIEW_TOOLS
    assert request.model == models().review
    assert request.role == "review"


def test_a_review_is_told_what_happened_to_the_branch_first(tmp_path: Path) -> None:
    runtime = StandInRuntime()

    build_run_review(runtime=runtime)(cwd=tmp_path, context="MOVED ONTO A CHANGED PREDECESSOR")

    assert runtime.request.prompt == f"MOVED ONTO A CHANGED PREDECESSOR\n\n{REVIEW_PROMPT}"


def test_a_rework_s_review_is_asked_for_as_one(tmp_path: Path) -> None:
    runtime = StandInRuntime()

    build_run_review(runtime=runtime, model=models().rework_review, role="rework_review")(
        cwd=tmp_path
    )

    assert runtime.request.role == "rework_review"
    assert runtime.request.model == models().rework_review
