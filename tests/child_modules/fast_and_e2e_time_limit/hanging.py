from collections.abc import Callable

import pytest


@pytest.mark.local_stack
def test_e2e_hangs(spin: Callable[[float], None]) -> None:
    spin(20)


def test_fast_hangs(spin: Callable[[float], None]) -> None:
    spin(20)
