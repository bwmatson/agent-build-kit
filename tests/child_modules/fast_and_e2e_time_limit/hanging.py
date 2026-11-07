from collections.abc import Callable

import pytest


@pytest.mark.e2e
def test_e2e_hangs(spin: Callable[[float], None]) -> None:
    spin(20)


def test_fast_hangs(spin_cpu: Callable[[float], None]) -> None:
    spin_cpu(20)
