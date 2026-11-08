from collections.abc import Callable, Iterator

import pytest


@pytest.fixture
def slow_teardown(spin_cpu: Callable[[float], None]) -> Iterator[None]:
    yield
    spin_cpu(20)


@pytest.fixture
def slow_setup(spin_cpu: Callable[[float], None]) -> None:
    spin_cpu(20)


def test_with_a_slow_teardown(slow_teardown: None) -> None:
    pass


def test_with_a_slow_setup(slow_setup: None) -> None:
    pass


def test_after_them() -> None:
    pass
