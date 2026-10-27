from collections.abc import Callable

import pytest


@pytest.mark.local_stack
def test_e2e_is_slow(spin: Callable[[float], None]) -> None:
    spin(3)


def test_fast_is_slow(spin: Callable[[float], None]) -> None:
    spin(3)
