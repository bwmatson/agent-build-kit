"""The overall result and the name helpers are read from the list of checks."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import (
    Check,
    CheckStatus,
    cancelled_names,
    failing_names,
    overall_result,
)

PASSED, FAILED = CheckStatus.PASSED, CheckStatus.FAILED
CANCELLED, PENDING = CheckStatus.CANCELLED, CheckStatus.PENDING


def checks(*pairs: tuple[str, CheckStatus]) -> tuple[Check, ...]:
    return tuple(Check(name=name, status=status) for name, status in pairs)


@pytest.mark.parametrize(
    ("statuses", "result"),
    [
        ([], "none"),
        ([PASSED], "passed"),
        ([PASSED, PASSED], "passed"),
        ([PENDING], "pending"),
        ([PASSED, PENDING], "pending"),
        ([FAILED], "failed"),
        ([PASSED, FAILED], "failed"),
        ([PENDING, FAILED], "failed"),
        ([FAILED, CANCELLED], "failed"),
        ([CANCELLED], "pending"),
        ([CANCELLED, CANCELLED], "pending"),
        ([CANCELLED, PENDING], "pending"),
    ],
)
def test_the_overall_result(statuses: list[CheckStatus], result: str) -> None:
    listed = checks(*((f"c{i}", status) for i, status in enumerate(statuses)))

    assert overall_result(listed) == result


def test_the_failing_names_are_the_failed_checks_sorted() -> None:
    listed = checks(("slow", FAILED), ("lint", PASSED), ("CI", FAILED), ("gone", CANCELLED))

    assert failing_names(listed) == ("CI", "slow")


def test_the_cancelled_names_are_the_cancelled_checks_sorted() -> None:
    listed = checks(("slow", CANCELLED), ("lint", FAILED), ("CI", CANCELLED), ("run", PENDING))

    assert cancelled_names(listed) == ("CI", "slow")


def test_no_checks_have_no_names() -> None:
    assert failing_names(()) == ()
    assert cancelled_names(()) == ()


def test_a_pending_check_is_neither_failing_nor_cancelled() -> None:
    listed = checks(("CI", PENDING))

    assert failing_names(listed) == cancelled_names(listed) == ()
