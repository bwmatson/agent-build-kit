"""A conflict event dispatched over a fake store, a fake base tip and a fake clock."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_in_force, pause_until
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW
from tests import fake_clock
from tests.factories import stored_unit
from tests.pr_poller_fakes import pull

PR = 4
UNIT = "add-marker/1"
PARENT = "parent/1"


class ConflictRig:
    """One unit in review at `pushed` `h1`, its pull request number 4, over a base whose tip is
    `tip`; `conflict()` dispatches what the poller sends for a conflict read now.

    `restack` is what the dispatch is given: by default a recorder that moves nothing, or, with
    `pushes`, pushes a new head as a clean move does. `claim` and `resume` default to the
    dispatch's own."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        stacked: bool = False,
        pushes: bool = False,
    ) -> None:
        self.clock = fake_clock.install(monkeypatch)
        self.began = self.clock.now()
        self.tip = "tip1"
        self.base_tip: Callable[[StoredUnit], str] = lambda unit: self.tip
        self.fork_point: Callable[[StoredUnit], str] = lambda unit: "fork1"
        self.store = UnitStore(tmp_path / "units.json")
        self.state_dir = tmp_path / "state"
        self.restacked: list[dict[str, Any]] = []
        self.pushes = pushes
        self.restack: events.Restack = self.record_restack
        self.claim: Callable[..., Any] | None = None
        self.resume: Callable[..., bool] | None = None
        self.lane: Any = None
        self.logged: list[str] = []
        parent = stored_unit(PARENT, change="parent")
        unit = stored_unit(UNIT, depends_on=(PARENT,) if stacked else ())
        self.store.upsert([parent, unit] if stacked else [unit])
        if stacked:
            self.store.set_state(PARENT, IN_REVIEW, pr=3, branch="spec/parent/1")
        self.store.set_state(UNIT, IN_REVIEW, pr=PR, branch="spec/add-marker/1")
        self.store.record_push(UNIT, "h1")

    def record_restack(self, **kwargs: Any) -> None:
        self.restacked.append(kwargs)
        if self.pushes:
            self.store.record_push(UNIT, f"moved-{len(self.restacked)}")

    def pause(self) -> None:
        """A usage pause in force, as the marker the pipeline writes."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        pause_until(
            datetime.now(UTC) + timedelta(hours=1),
            reason="usage window spent",
            marker=self.state_dir / PAUSE_MARKER,
        )

    def end_pause(self) -> None:
        """The pause is over: its marker is gone."""
        (self.state_dir / PAUSE_MARKER).unlink()

    def push(self, head: str) -> None:
        """The unit has pushed `head`, as a run of its own does."""
        self.store.record_push(UNIT, head)

    def back_in_review(self, head: str) -> None:
        """A rework has finished: the unit is in review again at `head`."""
        self.store.set_state(UNIT, IN_REVIEW)
        self.store.record_push(UNIT, head)

    def stored(self) -> StoredUnit:
        return self.store.get(UNIT)

    def dispatch(self) -> Callable[..., bool]:
        options: dict[str, Any] = {}
        if self.claim is not None:
            options["claim"] = self.claim
        if self.resume is not None:
            options["resume"] = self.resume
        if self.lane is not None:
            options["lane"] = self.lane
        return events.build_dispatch(
            self.store,
            restack=self.restack,
            base_tip=self.base_tip,
            fork_point=self.fork_point,
            paused=lambda: pause_in_force(self.state_dir),
            log=self.logged.append,
            **options,
        )

    def conflict(self, *, since: datetime | None = None, after: float = 300) -> bool:
        """Let `after` seconds pass, then offer a conflict read now; `since` is when the run of
        conflicting answers began."""
        self.clock.advance(after)
        return self.dispatch()(
            "conflict",
            PR,
            repo="app",
            pull=pull(False, PR),
            since=since or self.began,
            read_at=self.clock.now(),
        )

    def rework(self, reason: str, kind: Any) -> bool:
        """What the poller sends when a conflict begins, or is met on first sight."""
        return self.dispatch()("rework", PR, repo="app", reason=reason, pull=None, rework=kind)


def real_restack(
    rig: ConflictRig,
    tmp_path: Path,
    *,
    move: Callable[..., Moved],
    pushed: list[str],
    diff_changes: bool = False,
    unit_test: Callable[..., tuple[bool, str]] | None = None,
    comments: list[str] | None = None,
) -> events.Restack:
    """The stack move as `build_restack` does it, over a unit approved at `approved`, with the
    git, unit-test and the host stood in for: `pushed` collects what it pushes and `comments` the
    bodies it posts."""
    rig.store.record_approval(UNIT, "approved")
    diffs = iter(range(100))
    return events.build_restack(
        repos={"app": tmp_path / "app"},
        store=rig.store,
        root=tmp_path,
        move=move,
        unit_test=unit_test or (lambda **kwargs: (True, "")),
        push=lambda *args, **kwargs: pushed.append("pushed") or "newsha",
        retarget=lambda *args, **kwargs: None,
        comment=lambda pr, body, **kwargs: comments.append(body) if comments is not None else None,
        diff_id=lambda repo, base, branch: f"diff-{next(diffs) if diff_changes else 0}",
        head_of=lambda repo, branch: "approved",
        remote_head_of=lambda repo, branch: None,
    )
