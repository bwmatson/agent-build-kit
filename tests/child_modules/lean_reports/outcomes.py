"""Child tests that print and then pass, fail, error in a fixture, skip and xfail.

Their names start with `child_`: the outer test runs them with `python_functions=child_*`, so
the repository's own runs never mistake them for tests.
"""

import pytest


@pytest.fixture
def broken() -> None:
    print("printed by the broken fixture")
    raise AssertionError("fixture error on purpose")


def child_passes() -> None:
    print("printed by child_passes")


def child_fails() -> None:
    print("printed by child_fails")
    raise AssertionError("failing on purpose")


def child_errors(broken: None) -> None:
    print("printed by child_errors")


def child_skips() -> None:
    print("printed by child_skips")
    pytest.skip("skipped on purpose")


@pytest.mark.xfail(reason="not strict", strict=False)
def child_xpasses() -> None:
    print("printed by child_xpasses")


@pytest.mark.xfail(reason="expected")
def child_xfails() -> None:
    print("printed by child_xfails")
    raise AssertionError("expected failure")
