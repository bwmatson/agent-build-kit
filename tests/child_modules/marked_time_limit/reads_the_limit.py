import pytest


@pytest.mark.time_limit(5000)
def test_marked_runs_past_the_default(armed: list[float]) -> None:
    assert armed[-1] == 25000


@pytest.mark.time_limit(7000)
def test_marked_runs_past_its_own_limit(armed: list[float]) -> None:
    assert armed[-1] == 35000


def test_unmarked_beside_them(armed: list[float]) -> None:
    assert armed[-1] == 45000
