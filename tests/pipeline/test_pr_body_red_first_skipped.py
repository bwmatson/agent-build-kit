"""A check that did not run is not claimed: the verified list has no "seen to fail" line and no
failing-run line for a red result recorded as skipped (spec: tdd-loop)."""

from __future__ import annotations

from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.pr_body import verified_list
from agent_build_kit.pipeline.verdict import GateResult, VerdictFacts


def test_a_skipped_check_leaves_no_line_about_the_failing_run() -> None:
    facts = VerdictFacts(
        kind=TestTier.UNIT_TEST, red_first=GateResult.SKIPPED, unit_test=GateResult.PASSED
    )

    text = verified_list(facts, rounds=1)

    assert "seen to fail" not in text
    assert "failing run" not in text
