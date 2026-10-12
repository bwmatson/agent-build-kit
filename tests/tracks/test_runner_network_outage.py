"""A phase whose agent run ends on a network outage is reported and settled, as a rate
limit is: the track goes on to the next project instead of aborting."""

from __future__ import annotations

import pytest

from agent_build_kit.runtimes import AgentRequest, NetworkUnavailable
from agent_build_kit.tracks import runner
from tests.runtimes.stand_in import StandInRuntime
from tests.tracks.test_runner import github_checkout, inst  # noqa: F401 — fixture


def down(request: AgentRequest) -> None:
    raise NetworkUnavailable(
        "API Error: Can't reach the API server (EAI_AGAIN)", strength="strong", host="api.example"
    )


def test_a_track_goes_on_to_the_next_project_after_an_outage(
    inst,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
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
    agent = StandInRuntime(act=down)

    assert runner.run_track(inst, "propose", runtime=agent) == 1

    assert len(agent.requests) == 2, "the second project's phase still ran"
    assert sorted(settled) == ["app", "platform"]
