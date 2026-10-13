"""A poller over successive pages of pull requests, a fake clock and a fake store lookup."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.forges import PullRequest
from agent_build_kit.pipeline.pr_poller import Poller, PrState
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW
from tests import fake_clock
from tests.factories import stored_unit


def pull(mergeable: bool | None = None, number: int = 4) -> PullRequest:
    return PullRequest(
        number=number, head="spec/add-marker/1", base="main", state="open", mergeable=mergeable
    )


class PollerRig:
    """Polls answered from `answers` in order (the last repeating), with each
    event dispatched recorded as `(event, kwargs)`."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unit: StoredUnit) -> None:
        self.clock = fake_clock.install(monkeypatch)
        self.unit: StoredUnit | None = unit
        self.events: list[tuple[str, dict]] = []
        self.taken = True
        self.answer: bool | None = None
        self.path = tmp_path / "poll.json"
        self.poller = Poller(
            repo="app",
            state_path=self.path,
            list_prs=lambda: [pull(self.answer)],
            dispatch=self._dispatch,
            unit_of=lambda number: self.unit,
        )

    def _dispatch(self, event: str, number: int, **kwargs) -> bool:
        self.events.append((event, kwargs))
        return self.taken

    def poll(self, answer: bool | None, *, after: float = 300) -> None:
        """Let `after` seconds pass, then poll a host answering `answer`."""
        self.clock.advance(after)
        self.answer = answer
        self.poller.poll()

    def push(self, *, ago: float = 0) -> datetime:
        """The unit has pushed `ago` seconds before now; returns when."""
        when = self.clock.now() - timedelta(seconds=ago)
        assert self.unit is not None
        self.unit = self.unit.model_copy(update={"pushed": "abc123", "pushed_at": when})
        return when

    def seen(self) -> dict:
        return PrState.load(self.path)["4"]

    def names(self) -> list[str]:
        return [event for event, _ in self.events]


def in_review_unit() -> StoredUnit:
    return stored_unit(state=IN_REVIEW, pr=4, branch="spec/add-marker/1")
