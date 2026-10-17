"""A e2e-test whose runs park blocked runtimes, for the tests of what the node does with a
result that did not run every group (spec: e2e-runtime-parking)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.pipeline.e2e import E2eResult
from agent_build_kit.pipeline.e2e_holds import ORIGIN_FILE, Hold, Holds
from agent_build_kit.pipeline.unit_store import RequeueReason

GATE_CLEARED = ResumeEvent(
    kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="gate cleared"
)
# The commit the recorder's `head` answers once it has made one commit.
RAN = "sha-1"
FIRST_RUN = "FIRST-RUN-MARK the groups that could run"
SECOND_RUN = "SECOND-RUN-MARK the group that was parked"


@dataclass(frozen=True)
class Step:
    """What one e2e-test run answers: whether it passed, the runtimes it parked, its snapshot."""

    ok: bool = True
    parked: tuple[str, ...] = ()
    snapshot: str = FIRST_RUN
    sha: str = RAN


def holds_of(**reasons: str) -> Holds:
    """The splits held now, each with the reason given."""
    return Holds(
        held={
            name: Hold(
                split=name,
                reason=reason,
                origins=(ORIGIN_FILE,),
                since=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for name, reason in reasons.items()
        }
    )


class Parking:
    """E2e-test answering `steps` in turn (the last again once they are spent). Each run is
    recorded in the recorder's events, with the one group it was limited to, if any."""

    def __init__(self, events: list[str], *steps: Step) -> None:
        self.events, self.steps = events, list(steps)
        self.only: list[str | None] = []
        self.results_read = 0
        self._last = Step()

    def run(
        self, *, cwd: Path, base: str | None = None, only: str | None = None
    ) -> tuple[bool, str]:
        self.events.append("e2e-test")
        self.only.append(only)
        if self.steps:
            self._last = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        return self._last.ok, self._last.snapshot

    def result(self) -> E2eResult:
        self.results_read += 1
        step = self._last
        return E2eResult(
            sha=step.sha,
            passed=3,
            failed=0 if step.ok else 1,
            skipped=0,
            duration_seconds=1.5,
            command="uv run pytest -m local_stack",
            output=step.snapshot,
            parked=list(step.parked),
        )
