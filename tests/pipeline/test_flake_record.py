"""A flake is appended to a record in the state directory (spec: flaky-tests)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import Flake, FlakeCount, flake_record

FIRST = datetime(2026, 3, 1, 9, 30, tzinfo=UTC)


def flake(test: str = "tests/test_a.py::test_x", *, minutes: int = 0, **fields: str) -> Flake:
    return Flake(
        test=test,
        unit=fields.pop("unit", "feature/1"),
        command=fields.pop("command", "uv run pytest -n auto -q"),
        output=fields.pop("output", "FAILED tests/test_a.py::test_x - assert 0 == 1\n"),
        at=FIRST + timedelta(minutes=minutes),
        **fields,
    )


def test_a_flake_is_recorded_with_its_test_unit_command_output_and_time(
    installation: Installation,
) -> None:
    kept = flake(output="line one\n✗ line two with a non-ascii mark\n\nlast line")

    flake_record(installation).append(kept)

    assert flake_record(installation).entries() == [kept], "read back by a later reader"


def test_flakes_are_kept_in_the_order_they_were_found(installation: Installation) -> None:
    first, second = flake(unit="feature/1"), flake("tests/test_b.py::test_y", minutes=5)

    flake_record(installation).append(first)
    flake_record(installation).append(second)

    assert flake_record(installation).entries() == [first, second]


def test_nothing_recorded_is_an_empty_record(installation: Installation) -> None:
    assert flake_record(installation).entries() == []
    assert flake_record(installation).counts() == []


def test_each_flaky_test_is_counted_with_the_change_that_fixes_it(
    installation: Installation,
) -> None:
    record = flake_record(installation)
    record.append(flake(unit="feature/1", change="fix-flaky-test-x"))
    record.append(flake("tests/test_b.py::test_y", minutes=1, change="fix-flaky-test-y"))
    record.append(flake(unit="other/2", minutes=2, change="fix-flaky-test-x"))

    counts = flake_record(installation).counts()

    assert sorted(counts, key=lambda c: c.test) == [
        FlakeCount(test="tests/test_a.py::test_x", count=2, change="fix-flaky-test-x"),
        FlakeCount(test="tests/test_b.py::test_y", count=1, change="fix-flaky-test-y"),
    ]


def test_a_successor_fix_change_replaces_the_earlier_one_in_the_counts(
    installation: Installation,
) -> None:
    record = flake_record(installation)
    record.append(flake(change="fix-flaky-test-x"))
    record.append(flake(minutes=60, change="fix-flaky-test-x-2"))

    assert flake_record(installation).counts() == [
        FlakeCount(test="tests/test_a.py::test_x", count=2, change="fix-flaky-test-x-2")
    ]
