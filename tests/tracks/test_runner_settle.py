"""What a phase leaves in the planning repo: only its Markdown is committed, and
an interrupted phase is settled like a finished one."""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.runtimes import AgentRateLimited, AgentRequest
from agent_build_kit.tracks import runner
from tests.factories import git
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner_planning_repo import (  # noqa: F401 — fixtures
    branch_of,
    count,
    doing,
    inst,
    log_name,
    phase,
    remote,
    write_run_log,
)


def test_a_phase_that_hits_the_rate_limit_is_still_settled(inst: Installation) -> None:  # noqa: F811 — fixture
    planning = inst.root
    before = count(planning)

    def switch_then_limit(request: AgentRequest) -> None:
        git(planning, "checkout", "-q", "-b", "feature-y")
        write_run_log(inst)
        raise AgentRateLimited("window spent")

    assert phase(inst, StandInRuntime(act=switch_then_limit)) == 1

    assert branch_of(planning) == "main"
    assert count(planning) == before + 1
    assert git(planning, "show", f"main:{log_name(inst)}")
    assert git(planning, "branch", "--list", "feature-y") != ""


def test_only_the_phase_s_markdown_is_committed_not_the_tick_s_state(
    inst: Installation,  # noqa: F811 — fixture
) -> None:
    planning = inst.root
    state = inst.state_dir
    state.mkdir(parents=True, exist_ok=True)
    (state / "units.json").write_text("{}")
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "state")
    (state / "units.json").write_text('{"live": true}')
    (state / "paused.json").write_text("{}")

    phase(inst, doing(inst))

    assert git(planning, "show", "--name-only", "--format=", "main").splitlines() == [
        log_name(inst)
    ]
    status = git(planning, "status", "--porcelain").splitlines()
    assert sorted(line.split()[-1] for line in status) == [
        f"{state.name}/paused.json",
        f"{state.name}/units.json",
    ]
    assert runner.RUN_ID in git(planning, "log", "-1", "--format=%s", "main")
