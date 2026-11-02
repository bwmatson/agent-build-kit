"""Archiving a change rolls its ledger lines up; its `restack` lines are kept, as `metric`
lines are, so `abk restacks` still counts it (spec: restack-points, each restack decision is
recorded and summarised)."""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.usage_report import roll_up_change


def test_a_changes_restack_lines_survive_its_roll_up(workspace: Installation) -> None:
    for change in ("feature", "other"):
        spans.record_restack(
            spans.RestackRecord(
                at="2030-01-01T09:00:00+00:00",
                unit=f"{change}/1",
                change=change,
                point="before_pr",
                moved=True,
            ),
            lambda message: None,
        )
    ledger = workspace.state_dir / LEDGER_NAME

    roll_up_change(ledger, "feature")

    kept = spans.read_restacks(ledger)
    assert sorted(record.change for record in kept) == ["feature", "other"]
