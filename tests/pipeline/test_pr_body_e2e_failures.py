"""The failure listing is never cut to fit a description, and the unit's saved
feedback holds it when the cut output does not hold the first error."""

from pathlib import Path

from agent_build_kit.pipeline.e2e import TestFailure
from agent_build_kit.pipeline.pr_body import build_pr_body
from tests.e2e_failure_fakes import run_failing_e2e
from tests.factories import output_of, snapshot
from tests.factories import stored_unit as unit

FAILURES = [
    TestFailure(test=f"tests/live/test_module.py::test_case_{n:02d}", line=f"KeyError: 'P{n:02d}'")
    for n in range(30)
]


def _body(snap: str, limit: int | None) -> str:
    u = unit(tier="e2e-test", depends_on=())
    return build_pr_body(u, graph=[u], base="main", e2e_snapshot=snap, limit=limit)


def test_thirty_failed_tests_are_all_listed_whole_when_the_output_is_cut() -> None:
    output = output_of(6_000)
    snap = snapshot(output, failures=FAILURES)
    limit = len(_body(snapshot("", failures=FAILURES), None)) + 600

    body = _body(snap, limit)

    assert len(body) <= limit
    assert output[:200] not in body, "the output was cut"
    for failure in FAILURES:
        assert f"`{failure.test}` - {failure.line}" in body


def test_the_saved_feedback_holds_the_listing_when_the_output_does_not_hold_the_error(
    tmp_path: Path,
) -> None:
    snap = snapshot("only the last lines\n1 failed in 1s", failures=FAILURES[:4])

    feedback, _ = run_failing_e2e(tmp_path, snap)

    assert "KeyError" not in snap.split("<details>")[1]
    for failure in FAILURES[:4]:
        assert f"`{failure.test}` - {failure.line}" in feedback
