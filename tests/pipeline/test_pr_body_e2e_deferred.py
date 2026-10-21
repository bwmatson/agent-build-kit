"""The body of a unit that deferred its e2e-test run says so, in a section no limit cuts."""

from __future__ import annotations

from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.unit_store import E2eState
from tests.factories import follow_ups, output_of, snapshot
from tests.factories import stored_unit as unit

DEFERRED = "e2e-test deferred to verify"


def body_of(*, tier: str = "e2e-test", state: E2eState | None, limit: int | None = None) -> str:
    u = unit(tier=tier, depends_on=(), e2e_state=state)
    return build_pr_body(
        u,
        graph=[u],
        base="main",
        e2e_snapshot=snapshot(output_of(4_000)) if state != E2eState.DEFERRED else None,
        follow_ups=follow_ups(20),
        limit=limit,
    )


def test_a_deferred_unit_says_its_e2e_test_run_was_deferred_to_verify() -> None:
    body = body_of(state=E2eState.DEFERRED)

    assert DEFERRED in body
    assert "after the merge" in body
    assert "deployed change" in body


def test_a_deferred_unit_holds_no_e2e_results() -> None:
    body = body_of(state=E2eState.DEFERRED)

    assert "## e2e-test results" not in body
    assert "Not recorded" not in body


def test_the_deferred_text_survives_a_limit_far_under_the_natural_size() -> None:
    natural = body_of(state=E2eState.DEFERRED)

    body = body_of(state=E2eState.DEFERRED, limit=len(natural) // 2)

    assert len(body) <= len(natural) // 2
    assert DEFERRED in body
    assert "after the merge" in body


def test_a_unit_that_passed_keeps_its_results_section() -> None:
    body = body_of(state=E2eState.PASSED)

    assert "## e2e-test results" in body
    assert DEFERRED not in body
    assert DEFERRED in body_of(state=E2eState.DEFERRED), "only a deferred unit says so"


def test_a_unit_test_unit_keeps_its_verification_text() -> None:
    body = body_of(tier="unit-test", state=E2eState.NOT_REQUIRED)

    assert "No e2e-test run was required." in body
    assert DEFERRED not in body
    assert DEFERRED in body_of(state=E2eState.DEFERRED), "only a deferred unit says so"
