from collections.abc import Callable, Iterator

import pytest


@pytest.fixture(scope="module")
def module_tick(spin: Callable[[float], None]) -> None:
    spin(3)


@pytest.fixture
def slow_setup(spin: Callable[[float], None]) -> None:
    spin(3)


@pytest.fixture
def slow_teardown(spin: Callable[[float], None]) -> Iterator[None]:
    yield
    spin(3)


@pytest.mark.local_stack
def test_call_is_slow(spin: Callable[[float], None]) -> None:
    spin(3)


@pytest.mark.local_stack
def test_setup_is_slow(slow_setup: None) -> None:
    pass


@pytest.mark.local_stack
def test_teardown_is_slow(slow_teardown: None) -> None:
    pass


@pytest.mark.local_stack
def test_first_with_module_fixture(module_tick: None) -> None:
    pass


@pytest.mark.local_stack
def test_second_with_module_fixture(module_tick: None) -> None:
    pass
