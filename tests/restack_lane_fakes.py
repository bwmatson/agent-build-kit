"""What the restack lane's tests share: restacks that block on events, and a lane over
the real branch locks, so a claim held by a run is the one the lane meets."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import usage_guard, wiring
from agent_build_kit.pipeline.events import build_claim
from agent_build_kit.pipeline.restack_lane import RestackLane
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.runtimes import AgentRequest, AgentResult
from tests.conftest import make_installation
from tests.factories import git, init_repo, stored_unit
from tests.restack_turn_fakes import BRANCH, Rig
from tests.runtimes.stand_in import StandInRuntime
from tests.usage_host import Host

WAIT = 60


def units(count: int) -> list[StoredUnit]:
    return [stored_unit(f"feature/{number}", change="feature") for number in range(1, count + 1)]


def caused(unit_id: str, state: str, cause: Cause | None, **fields: Any) -> StoredUnit:
    """A stored unit in `state` whose last change out of running had `cause`, as the
    store records it in the unit's history."""
    history = (
        ({"state": state, "at": "2026-01-01T00:00:00+00:00", "cause": cause.value},)
        if cause
        else ()
    )
    return stored_unit(unit_id, change="feature", state=state, history=history, **fields)


class Events(dict[str, threading.Event]):
    """An event for each unit id, made when first asked for."""

    mutex = threading.Lock()

    def __missing__(self, unit_id: str) -> threading.Event:
        with self.mutex:
            return self.setdefault(unit_id, threading.Event())


class Restacks:
    """The lane's `move`: each unit's restack starts, notes it, and ends when released."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.finished: list[str] = []
        self.begun = Events()
        self.released = Events()
        self.mutex = threading.Lock()
        self.at_once = 0
        self.most_at_once = 0
        self.everything = False

    def __call__(self, unit: StoredUnit) -> None:
        with self.mutex:
            self.started.append(unit.id)
            self.at_once += 1
            self.most_at_once = max(self.most_at_once, self.at_once)
        self.begun[unit.id].set()
        assert self.everything or self.released[unit.id].wait(WAIT)
        with self.mutex:
            self.at_once -= 1
            self.finished.append(unit.id)

    def release(self, *unit_ids: str) -> None:
        for unit_id in unit_ids:
            self.released[unit_id].set()

    def release_all(self) -> None:
        """Every restack, those not yet started as well."""
        self.everything = True
        for event in list(self.released.values()):
            event.set()


def lane_over(
    locks: Path,
    move: Callable[[StoredUnit], None],
    *,
    cap: int = 2,
    owed: Callable[[list[StoredUnit]], Collection[str]] = lambda graph: (),
) -> RestackLane:
    return RestackLane(cap, move=move, claim=build_claim(locks), owed=owed)


def repo_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **limits: int) -> Installation:
    """`spec/feature/3` was cut from `main` before `main` moved: it does not hold its base."""
    inst = make_installation(
        tmp_path,
        planning={
            "state_dir": ".",
            "worktree_root": str(tmp_path.with_name(tmp_path.name + "-trees")),
        },
        limits=limits,
    )
    repo = init_repo(inst.checkouts["app"])
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a")
    git(repo, "branch", "spec/feature/3")
    (repo / "b.txt").write_text("b\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "b")
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
    return inst


def moved(inst: Installation) -> None:
    git(inst.checkouts["app"], "branch", "-f", "spec/feature/3", "main")


class Tracking(StandInRuntime):
    """A runtime with a usage window, as Claude Code has, so the guard is the one asked; it
    reports each call it finishes with the session it ran in, as the ledger's recorder is told."""

    supports_usage_tracking = True
    supports_session_resume = True

    def run(self, request: AgentRequest) -> AgentResult:
        result = super().run(request)
        result = result.model_copy(update={"session_id": request.resume_session or "sess-1"})
        if request.on_result:
            request.on_result(result)
        return result


def tracked_rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: Host) -> Rig:
    """The conflicting repository of `Rig`, its child owed a restack onto `main`, over an agent
    with a usage window and the usage endpoint's cache in the installation's state directory."""
    rig = Rig(tmp_path, monkeypatch)
    rig.runtime = Tracking
    rig.prepared()  # the agent the lane's resolver reaches
    host.keep_in(rig.installation.state_dir)
    rig.store.set_state(rig.child.id, PLANNED, cause=Cause.BASE_CHANGED, branch=BRANCH)
    return rig


def asked_of_the_guard(monkeypatch: pytest.MonkeyPatch) -> list[usage_guard.Decision]:
    """Every decision of the guard from now on, in the order it was asked, whichever module
    the lane reaches `decide_start` through."""
    real = usage_guard.decide_start
    decisions: list[usage_guard.Decision] = []

    def spy(**kwargs):
        decisions.append(real(**kwargs))
        return decisions[-1]

    for module in (usage_guard, wiring, cli):
        monkeypatch.setattr(module, "decide_start", spy)
    return decisions


def moved_onto_main(rig: Rig, branch: str) -> bool:
    held = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "main", branch], cwd=rig.repo, check=False
    )
    return held.returncode == 0


def restack(rig: Rig) -> None:
    """Every unit owed a restack, moved by the lane `abk tick` builds."""
    with cli.build_restack_lane(rig.installation, rig.store) as lane:
        lane.scan(rig.store.all())
