from collections.abc import Callable

import pytest


@pytest.mark.e2e
@pytest.mark.time_limit(1)
def test_e2e_keeps_the_e2e_limit(spin: Callable[[float], None]) -> None:
    spin(3)
