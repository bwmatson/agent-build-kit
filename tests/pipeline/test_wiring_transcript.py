"""A unit's agent steps leave a transcript under the state directory.

The `claude` process is faked at its stream-json boundary; everything between
the step and the file on disk is the real wiring.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.config import models
from agent_build_kit.pipeline.gateway_usage import attribution
from agent_build_kit.pipeline.transcript import read_transcripts, transcript_dir
from agent_build_kit.pipeline.wiring import build_run
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from tests.conftest import make_installation
from tests.factories import unit
from tests.runtimes.claude_cli import FakeClaude, finished_build

UNIT = "add-marker/1"


def step(tmp_path: Path, **limits: int) -> Path:
    """Run one implement step of `UNIT` at node `review`, round 2; the state directory."""
    planning = tmp_path / "planning"
    installation = make_installation(planning, limits=limits)
    tree = tmp_path / "tree"
    tree.mkdir()
    run = build_run(
        runtime=ClaudeCodeRuntime(execute=FakeClaude(stdout=finished_build(tree, "Done."))),
        planning_repo=planning,
        record_for=(unit(UNIT, change="add-marker"), transcript_dir(installation.state_dir)),
    )
    token = attribution.set(f"{UNIT}:review:2")
    try:
        run("Implement it.", cwd=tree, model=models().implement)
    finally:
        attribution.reset(token)
    return installation.state_dir


def test_a_step_is_recorded_under_the_unit_node_and_round_that_made_it(tmp_path: Path) -> None:
    state = step(tmp_path)

    (path,) = transcript_dir(state).iterdir()
    assert path.name.startswith("add-marker-01-")
    assert path.name.endswith("-review-2.jsonl")
    events = read_transcripts(transcript_dir(state), UNIT)
    assert events
    assert {(e.unit, e.node, e.round) for e in events} == {(UNIT, "review", 2)}


def test_the_configured_result_limit_is_what_cuts_a_tool_result(tmp_path: Path) -> None:
    state = step(tmp_path, transcript_result_chars=5)

    (result,) = [
        e for e in read_transcripts(transcript_dir(state), UNIT) if e.kind == "tool_result"
    ]

    assert result.truncated is not None and result.truncated > 5
    assert result.text.split("\n")[0] == result.text[:5]
    assert "cut" in result.text


def test_a_step_outside_a_node_is_recorded_under_its_role_in_round_zero(tmp_path: Path) -> None:
    planning = tmp_path / "planning"
    installation = make_installation(planning)
    tree = tmp_path / "tree"
    tree.mkdir()
    run = build_run(
        runtime=ClaudeCodeRuntime(execute=FakeClaude(stdout=finished_build(tree, "Done."))),
        planning_repo=planning,
        record_for=(unit(UNIT, change="add-marker"), transcript_dir(installation.state_dir)),
    )

    run("Implement it.", cwd=tree, model=models().implement)

    (path,) = transcript_dir(installation.state_dir).iterdir()
    assert path.name.endswith("-implement-0.jsonl")
