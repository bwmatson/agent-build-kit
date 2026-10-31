"""A phase whose agent run meets a rejected login is reported and settled, as an outage is: the
track goes on to the next project instead of ending with a traceback."""

from __future__ import annotations

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.runtimes import AgentRequest, LoginRejected
from agent_build_kit.tracks import runner
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner import github_checkout, inst  # noqa: F401 — fixture


def rejected(request: AgentRequest) -> None:
    raise LoginRejected(Account.default(), "OAuth access token has expired")


def test_a_track_goes_on_to_the_next_project_after_a_rejected_login(
    inst,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    github_checkout(inst.repo("app").path, "example/app")
    github_checkout(inst.repo("platform").path, "example/platform")
    monkeypatch.setattr(runner, "repo_reachable", lambda name, inst: True)
    monkeypatch.setattr(runner, "has_headroom", lambda: True)
    monkeypatch.setattr(runner, "pull_planning", lambda inst: True)
    monkeypatch.setattr(runner, "pull", lambda path, branch: True)
    monkeypatch.setattr(runner, "record_planning", lambda inst: object())
    settled: list[str] = []
    monkeypatch.setattr(
        runner,
        "settle_planning",
        lambda inst, before, project, name: settled.append(project.name) or True,
    )
    agent = StandInRuntime(act=rejected)

    assert runner.run_track(inst, "propose", runtime=agent) == 1

    assert len(agent.requests) == 2, "the second project's phase still ran"
    assert sorted(settled) == ["app", "platform"]
    assert "stopped" in capsys.readouterr().out
