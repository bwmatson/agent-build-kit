"""A unit whose push the code host refuses, or cannot reach, is parked, not failed, and
resumes at its push. A fetch the host refuses is noted and the run goes on.

Run through the real run handler with the real `push_with_lease` over a stand-in `git`; the
reachability probe is the one `test_network_outage_parking` replaces.
"""

from __future__ import annotations

import subprocess
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline import restack, wiring
from agent_build_kit.pipeline.git_output import FetchFailed, TransportFailure
from agent_build_kit.pipeline.network_probe import Reachability
from agent_build_kit.pipeline.restack import push_with_lease
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, PLANNED, in_progress
from tests.factories import unit
from tests.pipeline.test_git_host_outage import (
    PERMISSION_DENIED,
    UNREACHABLE,
    FailingGit,
)
from tests.pipeline.test_git_output import recorded
from tests.pipeline.test_network_outage_parking import UNIT, Probe, build_once, fresh_store
from tests.runner_fakes import Recorder, make_runner

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Probe:
    return Probe(monkeypatch)


class Remote:
    """What the push meets: a failing git until `up()`, then the recorder's own push."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, recorder: Recorder, failing: FailingGit):
        self.recorder, self.failing, self.pushes = recorder, failing, 0
        monkeypatch.setattr(restack.shell, "has_origin", lambda repo: True)
        monkeypatch.setattr(restack, "git", failing)
        self.is_up = False

    def up(self) -> None:
        self.is_up = True

    def push(self, branch: str, *, cwd: Path) -> str:
        self.pushes += 1
        if self.is_up:
            return self.recorder.push(branch, cwd=cwd)
        return push_with_lease(cwd, branch, last_pushed=None)


def park_at_the_push(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failing: FailingGit
) -> tuple[Any, Recorder, Remote]:
    store = fresh_store(tmp_path)
    recorder = Recorder(store)
    remote = Remote(monkeypatch, recorder, failing)
    build_once(tmp_path, monkeypatch, store, recorder=recorder, push=remote.push)
    return store, recorder, remote


def test_a_push_the_host_refuses_parks_the_unit_for_the_code_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store, recorder, _ = park_at_the_push(tmp_path, monkeypatch, FailingGit(PERMISSION_DENIED))

    parked = store.get(UNIT)
    assert (parked.state, parked.cause, parked.step) == (PLANNED, "host_unavailable", "push")
    assert "Permission denied (publickey)" in parked.note
    assert parked.parked_attempts == 1
    assert parked.branch, "the branch is kept"
    assert in_progress(parked), "and so is the unit's place"
    assert recorder.made == 2, "its tests commit and its implementation commit were made"
    assert recorder.remote == [], "and nothing was pushed"
    assert probe.asked == [], "a refusal is the host's own word; nothing to sort"


@pytest.mark.parametrize(
    ("reached", "cause"),
    [
        (Reachability(api=False, control=False), "network_unavailable"),
        (Reachability(api=False, control=True), "host_unavailable"),
        (Reachability(api=True, control=True), "host_unavailable"),
    ],
    ids=["control-down", "host-down-control-up", "host-answers-again"],
)
def test_a_push_that_cannot_reach_the_host_is_sorted_by_the_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe: Probe,
    reached: Reachability,
    cause: str,
) -> None:
    probe.answer = reached

    store, _, _ = park_at_the_push(
        tmp_path, monkeypatch, FailingGit(UNREACHABLE["a timed-out connect"])
    )

    parked = store.get(UNIT)
    assert (parked.state, parked.cause, parked.step) == (PLANNED, cause, "push")
    assert (probe.asked, probe.ports) == (["github.com"], [22])


@pytest.mark.parametrize(
    "failing",
    [
        FailingGit("", stdout="!\trefs/heads/b:refs/heads/b\t[rejected] (stale info)\n"),
        FailingGit(
            recorded("push_hook_declined").stderr, stdout=recorded("push_hook_declined").stdout
        ),
        FailingGit(recorded("push_unrelated_failure").stderr),
    ],
    ids=["stale-lease", "hook-declined", "unclassified"],
)
def test_a_push_that_is_no_outage_still_fails_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe, failing: FailingGit
) -> None:
    store, _, _ = park_at_the_push(tmp_path, monkeypatch, failing)

    assert store.get(UNIT).state == FAILED
    assert probe.asked == []


def test_a_unit_parked_at_its_push_resumes_there_without_building_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    recorder = Recorder(store)
    remote = Remote(monkeypatch, recorder, FailingGit(PERMISSION_DENIED))
    build_once(tmp_path, monkeypatch, store, recorder=recorder, push=remote.push)
    built = list(recorder.events)
    assert store.get(UNIT).cause == "host_unavailable"

    remote.up()
    build_once(tmp_path, monkeypatch, store, recorder=recorder, push=remote.push)

    assert store.get(UNIT).state == IN_REVIEW
    assert store.get(UNIT).parked_attempts == 0
    assert remote.pushes == 2
    later = recorder.events[len(built) :]
    assert not [e for e in later if e.startswith(("claude:", "commit:", "review"))], later


# --- the fetch -------------------------------------------------------------------------


def refused_fetch(unit_: Any) -> None:
    raise FetchFailed(
        PERMISSION_DENIED.strip(),
        TransportFailure(kind="refused", message=PERMISSION_DENIED.strip()),
    )


def test_a_fetch_the_host_refuses_is_noted_and_the_run_goes_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    recorder = Recorder(store)
    noted: list[tuple[str, TransportFailure]] = []

    build_once(
        tmp_path,
        monkeypatch,
        store,
        recorder=recorder,
        fetch=refused_fetch,
        note_host_outage=lambda unit_, failure: noted.append((unit_.id, failure)),
    )

    assert store.get(UNIT).state == IN_REVIEW, "the unit is not parked"
    assert noted and {u for u, _ in noted} == {UNIT}
    assert {failure.kind for _, failure in noted} == {"refused"}
    assert any("fetch failed, going on with the refs it has" in line for line in recorder.logged)


def test_a_fetch_that_could_not_reach_the_host_is_noted_too(tmp_path: Path) -> None:
    store = fresh_store(tmp_path)
    recorder = Recorder(store)
    noted: list[str] = []

    def unreachable(unit_: Any) -> None:
        said = UNREACHABLE["a name that does not resolve"]
        raise FetchFailed(said, TransportFailure(kind="unreachable", message=said))

    runner = make_runner(
        store,
        recorder,
        tmp_path,
        fetch=unreachable,
        note_host_outage=lambda unit_, failure: noted.append(failure.kind),
    )

    runner.fetch_quietly(store.get(UNIT))

    assert noted == ["unreachable"]


@pytest.mark.parametrize(
    "error",
    [RuntimeError("fetch exploded"), FetchFailed("fatal: bad object", None)],
    ids=["plain", "not-an-outage"],
)
def test_any_other_fetch_failure_is_logged_and_noted_as_no_outage(
    tmp_path: Path, error: Exception
) -> None:
    store = fresh_store(tmp_path)
    recorder = Recorder(store)
    noted: list[object] = []

    def broken(unit_: Any) -> None:
        raise error

    runner = make_runner(
        store, recorder, tmp_path, fetch=broken, note_host_outage=lambda u, f: noted.append(f)
    )

    runner.fetch_quietly(store.get(UNIT))

    assert noted == []
    assert any("fetch failed, going on with the refs it has" in line for line in recorder.logged)


def test_the_real_fetch_raises_what_the_host_said_classified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def failing(repo: Path, *args: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 128, "", PERMISSION_DENIED)

    monkeypatch.setattr(wiring, "git", failing)
    monkeypatch.setattr(wiring, "has_origin", lambda repo: True)
    fetch = wiring.build_fetch({unit().repo: tmp_path}, turn=lambda repo: nullcontext())

    with pytest.raises(FetchFailed) as raised:
        fetch(unit())

    assert raised.value.failure is not None
    assert raised.value.failure.kind == "refused"
    assert "Permission denied (publickey)" in str(raised.value)


def test_the_fetch_runs_in_git_s_fixed_locale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Under a translated locale the refusal's words would not match."""
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    envs: list[dict[str, str] | None] = []

    def fetching(repo: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        envs.append(kwargs.get("env"))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(wiring, "git", fetching)
    monkeypatch.setattr(wiring, "has_origin", lambda repo: True)

    wiring.build_fetch({unit().repo: tmp_path}, turn=lambda repo: nullcontext())(unit())

    assert len(envs) == 1 and envs[0] is not None
    assert (envs[0]["LC_ALL"], envs[0]["LANGUAGE"]) == ("C", "C")


def test_the_real_fetch_of_an_unrelated_failure_carries_no_outage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        wiring,
        "git",
        lambda repo, *args, **kw: subprocess.CompletedProcess(args, 128, "", "fatal: bad object"),
    )
    monkeypatch.setattr(wiring, "has_origin", lambda repo: True)
    fetch = wiring.build_fetch({unit().repo: tmp_path}, turn=lambda repo: nullcontext())

    with pytest.raises(FetchFailed) as raised:
        fetch(unit())

    assert raised.value.failure is None
