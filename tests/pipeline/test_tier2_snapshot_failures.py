"""The snapshot lists every failed test above the `<details>` block."""

from agent_build_kit.pipeline.e2e import TestFailure, Tier2Result, build_snapshot

FAILURES = [
    TestFailure(test=f"tests/live/test_a.py::test_{n}", line=f"KeyError: 'PORT{n}'")
    for n in range(4)
]


def _result(failures: list[TestFailure]) -> Tier2Result:
    return Tier2Result(
        sha="abcdef0123",
        passed=2,
        failed=len(failures),
        skipped=0,
        duration_seconds=1.5,
        command="uv run pytest -m local_stack",
        output="the cut output",
        failures=failures,
    )


def test_every_failed_test_is_listed_above_the_details_block_in_order() -> None:
    snapshot = build_snapshot(_result(FAILURES))

    head = snapshot[: snapshot.index("<details>")]
    assert "**Failed:** 4 of 6 tests" in head
    positions = [head.index(f"`{f.test}` - {f.line}") for f in FAILURES]
    assert positions == sorted(positions)


def test_a_pass_shows_no_listing() -> None:
    snapshot = build_snapshot(_result([]))

    assert "**Failed:**" not in snapshot
    assert "**Failed:**" in build_snapshot(_result(FAILURES))


def test_a_stored_result_without_the_new_fields_still_loads() -> None:
    stored = _result([]).model_dump_json(exclude={"failures"})

    loaded = Tier2Result.model_validate_json(stored)

    assert loaded.failures == []
    assert "**Failed:**" not in build_snapshot(loaded)
    again = Tier2Result.model_validate_json(_result(FAILURES).model_dump_json())
    assert again.failures == FAILURES
    assert f"`{FAILURES[0].test}` - {FAILURES[0].line}" in build_snapshot(again)
