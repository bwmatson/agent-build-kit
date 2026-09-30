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
from tests.runtimes.claude_cli import FakeClaude, record, refused_record
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
    assert request.denied_tools.endswith("Bash(rm *)")
    assert "Bash(gh pr merge*)" in request.denied_tools, (
        "a track phase is denied every forge's way of merging, whatever "
        "tracks.disallowed_tools happens to name"
    )
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
        "--disallowedTools": runner.denied_tools_value("Bash(rm *)"),
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


# What the CLI hands back for each refusal, and what the log must say of it.
REFUSALS = {
    "a spent window": (
        dict(stdout=refused_record("Claude AI usage limit reached|1919763200"), returncode=1),
        "usage limit reached",
    ),
    "an interruption": (dict(returncode=-15), "killed by signal 15"),
}


@pytest.mark.parametrize("answer, said", REFUSALS.values(), ids=REFUSALS.keys())
def test_a_refused_phase_is_reported_never_raised(
    inst: Installation, answer: dict, said: str, capsys
) -> None:
    """A phase the runtime refused — the window spent, or the process
    killed — is logged as stopped, saying why, and fails the phase without
    raising. It keeps no raw output file: a refusal is not a run, and what
    the CLI said is all it has, which the log line carries whole."""
    fake = FakeClaude(**answer)

    assert runner.implement(inst, project(inst), runtime=ClaudeCodeRuntime(execute=fake)) == 1

    out = capsys.readouterr().out
    assert "[app] implement phase stopped" in out
    assert said in out
    assert not (runner.raw_output_dir(inst) / f"{runner.RUN_ID}-app-implement.json").exists()


@pytest.mark.parametrize("answer, said", REFUSALS.values(), ids=REFUSALS.keys())
def test_a_refused_discovery_still_runs_implement(
    inst: Installation, answer: dict, said: str, capsys
) -> None:
    """The documented contract: a track never raises, and the implement pass
    after a refused discovery phase still runs."""
    fake = FakeClaude(**answer)
    assert (
        runner.DISPATCH["improve"](
            inst, project(inst), None, runtime=ClaudeCodeRuntime(execute=fake)
        )
        == 1
    )

    assert ["--worktree" in argv for argv, _ in fake.calls] == [False, True]
    stopped = [line for line in capsys.readouterr().out.splitlines() if "phase stopped" in line]
    assert len(stopped) == 2
    assert "[app] improve phase stopped" in stopped[0]
    assert "[app] implement phase stopped" in stopped[1]
    assert all(said in line for line in stopped)


def test_a_dry_run_on_another_runtime_prints_the_request_and_runs_nothing(
    inst: Installation, capsys
) -> None:
    """Not a `claude` command: what the runtime would be asked, prompt elided."""
    runtime = StandInRuntime()

    assert runner.implement(inst, project(inst), dry_run=True, runtime=runtime) == 0

    out = capsys.readouterr().out
    assert "# Mission: implement phase — project `app`" in out
    assert "implement: stand_in request (prompt elided)" in out
    assert "'model': 'haiku'" in out
    assert f"'worktree': 'abk-{runner.RUN_ID}'" in out
    assert "claude -p" not in out
    assert runtime.requests == []
    assert not runner.raw_output_dir(inst).exists()


def test_with_no_runtime_given_a_phase_uses_the_active_one(inst: Installation) -> None:
    """Not a `claude` process of its own: the default is the workspace's
    runtime, whose real executor the suite refuses."""
    with pytest.raises(AssertionError, match="inject `execute=`"):
        runner.implement(inst, project(inst))
