import pytest


@pytest.mark.time_limit(5000)
def test_marked_runs_past_the_default(armed: list[float]) -> None:
    assert armed[-1] == 5000


@pytest.mark.time_limit(7000)
def test_marked_runs_past_its_own_limit(armed: list[float]) -> None:
    assert armed[-1] == 7000


def test_unmarked_beside_them(armed: list[float]) -> None:
    assert armed[-1] == 9000
