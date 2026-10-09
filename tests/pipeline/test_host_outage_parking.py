"""A step that cannot reach the code host parks its unit; any other failure fails it.

The unit's pull request is opened through the real forge over a stand-in host
answering at the HTTP boundary, so the error the step gives up with is the one the
retry layer raises. Every failure leaves its step and error text on the unit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.resilient import ResilientForge, RetryPolicy
from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.settings import settings
from tests.conftest import make_installation
from tests.factories import unit
from tests.fake_clock import FakeClock
from tests.forges.github_host import GitHubHost, answer, refusal
from tests.runner_fakes import Recorder, make_runner

pytestmark = pytest.mark.usefixtures("scripted_engine")

UNIT = unit().id
REPO = RepoId(forge="github", account="example", name="app")
PULLS = "/repos/example/app/pulls"
ATTEMPTS = 3


def build_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, store: UnitStore, **overrides: Any
) -> Recorder:
    inst = make_installation(tmp_path, planning={"state_dir": "."})
    # After the installation, which reloads the settings.
    monkeypatch.setattr(settings, "gh_token", "gh-secret")
    clear_credentials()
    recorder = Recorder(store)
    runner = make_runner(store, recorder, tmp_path, **overrides)
    monkeypatch.setattr(cli, "build_runner", lambda u, **kw: runner)

    assert cli.build_unit(inst, store.get(UNIT), store=store) is True
    return recorder


def fresh_store(tmp_path: Path) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return store


def open_pr_over(host: GitHubHost):
    clock = FakeClock()
    forge = ResilientForge(
        GitHubForge(http=host),
        RetryPolicy(attempts=ATTEMPTS, deadline_seconds=1000.0),
        clock,
        clock.advance,
    )

    def open_pr(u: Any, *, body: str, base: str, cwd: Path, **more: str) -> int:
        return forge.create_pr(REPO, head=f"spec/{u.id}", base=base, title=u.title, body=body)

    return open_pr


def down() -> GitHubHost:
    return GitHubHost(
        routes={
            ("POST", PULLS): refusal(500, "Server Error"),
            ("GET", PULLS): answer([]),
        }
    )


def test_a_pull_request_create_answered_500_every_time_parks_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fresh_store(tmp_path)

    recorder = build_once(tmp_path, monkeypatch, store, open_pr=open_pr_over(down()))

    stored = store.get(UNIT)
    assert stored.state == PLANNED, "the work is fine; only the host is down"
    assert stored.cause is Cause.HOST_UNAVAILABLE
    assert stored.step == "open_pr"
    assert "host unavailable after 3 attempts" in stored.note
    assert stored.parked_attempts == 1
    assert "push" in recorder.events, "approved and pushed before the host went down"
    assert stored.approved and stored.approved == stored.pushed


def test_a_unit_parked_again_counts_the_parkings_in_a_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fresh_store(tmp_path)
    open_pr = open_pr_over(down())
    build_once(tmp_path, monkeypatch, store, open_pr=open_pr)

    build_once(tmp_path, monkeypatch, store, open_pr=open_pr)

    assert store.get(UNIT).parked_attempts == 2


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("the forge said no"),
        KeyError("number"),
        ValueError("not a pull request"),
        OSError("disk full"),
        ZeroDivisionError("division by zero"),
    ],
    ids=lambda e: type(e).__name__,
)
@pytest.mark.parametrize("step", ["push", "open_pr"])
def test_a_step_that_raises_another_error_fails_the_unit_with_its_text_and_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, step: str
) -> None:
    def raises(*args: Any, **kwargs: Any) -> Any:
        raise error

    store = fresh_store(tmp_path)

    build_once(tmp_path, monkeypatch, store, **{step: raises})

    stored = store.get(UNIT)
    assert stored.state == FAILED
    assert stored.cause is Cause.FAILED
    assert stored.step == step
    assert type(error).__name__ in stored.note
    assert str(error) in stored.note
    assert stored.parked_attempts == 0, "a failure is not a parking"


def test_a_parked_unit_resumes_at_its_step_once_the_host_is_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = fresh_store(tmp_path)
    build_once(tmp_path, monkeypatch, store, open_pr=open_pr_over(down()))
    assert store.get(UNIT).cause is Cause.HOST_UNAVAILABLE
    up = GitHubHost(routes={("POST", PULLS): answer({"number": 9}, 201)})

    recorder = build_once(tmp_path, monkeypatch, store, open_pr=open_pr_over(up))

    assert len(up.calls("POST", PULLS)) == 1
    for step in ("push", "tier1", "tier2", "review"):
        assert step not in recorder.events
    assert not [event for event in recorder.events if event.startswith("claude:")]
    stored = store.get(UNIT)
    assert (stored.state, stored.pr) == (IN_REVIEW, 9)
    assert stored.parked_attempts == 0


def test_the_step_of_a_failure_is_forgotten_once_the_unit_runs_again(tmp_path: Path) -> None:
    store = fresh_store(tmp_path)
    store.record_step(UNIT, "push")
    store.set_state(UNIT, FAILED, cause=Cause.FAILED)
    assert store.get(UNIT).step == "push"

    store.set_state(UNIT, RUNNING)
    store.set_state(UNIT, IN_REVIEW, pr=3)

    assert store.get(UNIT).step == ""
