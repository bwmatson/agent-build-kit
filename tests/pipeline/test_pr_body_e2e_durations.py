"""The durations listing is never cut to fit a description: only the output is (spec:
e2e-time-is-recorded-per-test)."""

from agent_build_kit.pipeline.e2e import E2eResult, build_snapshot
from agent_build_kit.pipeline.pr_body import build_pr_body
from tests.e2e_duration_fakes import E2E, timed
from tests.factories import output_of
from tests.factories import stored_unit as unit

ENTRIES = [timed(900.0 - 10 * n, f"{E2E}::test_case_{n:02d}") for n in range(12)]


def _snapshot(output: str) -> str:
    return build_snapshot(
        E2eResult(
            sha="abcdef0123",
            passed=12,
            failed=0,
            skipped=0,
            duration_seconds=1.5,
            command="uv run pytest -m local_stack",
            output=output,
            durations=ENTRIES,
        )
    )


def _body(snap: str, limit: int | None) -> str:
    u = unit(tier="e2e-test", depends_on=())
    return build_pr_body(u, graph=[u], base="main", e2e_snapshot=snap, limit=limit)


def test_twelve_entries_are_all_listed_whole_when_the_output_is_cut() -> None:
    output = output_of(6_000)
    limit = len(_body(_snapshot(""), None)) + 600

    body = _body(_snapshot(output), limit)

    assert len(body) <= limit
    assert output[:200] not in body, "the output was cut"
    for entry in ENTRIES:
        assert f"`{entry.test}`" in body
    assert "Slowest" in body
