"""The scheduled tracks reach their agent through the runtime seam.

The runner used to build a fourth `claude` argv of its own and run it through
a module attribute its tests had to replace. A track phase is now an agent
request like any other step's, handed to a runtime the caller can supply —
with the model and the tool lists still read from the tracks configuration,
and, under Claude Code, the very command the runner sent before.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRequest
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.tracks import runner
from tests.runtimes.claude_cli import FakeClaude, record
from tests.runtimes.stand_in import StandInRuntime
from tests.runtimes.test_claude_code_argv import flags
from tests.tracks.test_runner import make_installation, project

TRACKS = {"model": "haiku", "allowed_tools": "Read Grep", "disallowed_tools": "Bash(rm *)"}


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(tmp_path / "planning", tracks=TRACKS)


def test_a_phase_runs_through_the_runtime_it_is_given(inst: Installation) -> None:
    """The phase's model and tools come from the tracks configuration, its
    prompt is the rendered playbook, and it names its own worktree off the
    project's checkout, with the planning repo readable for its run log."""
    runtime = StandInRuntime(raw='{"type": "result"}')
    app = project(inst)

    assert runner.implement(inst, app, runtime=runtime) == 0

    request = runtime.request
    assert request.prompt == runner.render_prompt(inst, app, "implement")
    assert request.cwd == app.path
    assert request.add_dirs == (inst.root,)
    assert request.model == "haiku"
    assert request.allowed_tools == "Read Grep"
    assert request.denied_tools == "Bash(rm *)"
    assert request.permission_mode == "edit"
    assert request.worktree == f"abk-{runner.RUN_ID}"
    assert request.keep_record is True


def test_a_phase_keeps_the_runtime_s_whole_record(inst: Installation) -> None:
    runtime = StandInRuntime(answer="done", raw='{"type": "result", "result": "done"}')

    runner.implement(inst, project(inst), runtime=runtime)

    output = runner.raw_output_dir(inst) / f"{runner.RUN_ID}-app-implement.json"
    assert output.read_text() == '{"type": "result", "result": "done"}'


def test_under_claude_code_a_phase_sends_the_command_it_sent_before(inst: Installation) -> None:
    """The same flags `build_command` assembled from the tracks
    configuration, run in the project's checkout, and the JSON record it
    printed kept as the raw output."""
    app = project(inst)
    fake = FakeClaude(stdout=record("Opened one PR."))

    assert runner.implement(inst, app, runtime=ClaudeCodeRuntime(execute=fake)) == 0

    prompt = runner.render_prompt(inst, app, "implement")
    assert flags(fake.argv, prompt) == {
        "-p": None,
        "--worktree": f"abk-{runner.RUN_ID}",
        "--add-dir": str(inst.root),
        "--permission-mode": "acceptEdits",
        "--allowedTools": "Read Grep",
        "--disallowedTools": "Bash(rm *)",
        "--model": "haiku",
        "--output-format": "json",
    }
    assert fake.calls[0][1] == app.path
    output = runner.raw_output_dir(inst) / f"{runner.RUN_ID}-app-implement.json"
    assert output.read_text() == fake.stdout


def test_a_discovery_phase_names_no_worktree(inst: Installation) -> None:
    """Health, improve and recommend read; only implement makes a checkout."""
    runtime = StandInRuntime()

    runner.health(inst, project(inst), runtime=runtime)

    assert runtime.request.worktree is None
    assert runtime.request.model == "haiku"


def test_health_s_early_implement_uses_the_same_runtime(inst: Installation) -> None:
    """A new finding runs implement straight away — through the runtime the
    track was given, not a default one."""
    app = project(inst)

    def report_attention(request: AgentRequest) -> None:
        if request.worktree is None:
            log = runner.run_log(inst, app, "health")
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("# Health\n\n**Status:** ATTENTION — a new finding\n")

    runtime = StandInRuntime(act=report_attention)

    assert runner.health(inst, app, runtime=runtime) == 0
    assert [r.worktree for r in runtime.requests] == [None, f"abk-{runner.RUN_ID}"]


def test_a_failed_discovery_still_runs_implement_through_the_runtime(inst: Installation) -> None:
    """A phase that fails is reported, never raised, and the implement pass
    after it still runs."""
    runtime = StandInRuntime(ok=False, error="claude exited 3: budget exhausted")

    assert runner.DISPATCH["improve"](inst, project(inst), None, runtime=runtime) == 1
    assert [r.worktree for r in runtime.requests] == [None, f"abk-{runner.RUN_ID}"]


def test_with_no_runtime_given_a_phase_uses_the_active_one(inst: Installation) -> None:
    """Not a `claude` process of its own: the default is the workspace's
    runtime, whose real executor the suite refuses."""
    with pytest.raises(AssertionError, match="inject `execute=`"):
        runner.implement(inst, project(inst))
