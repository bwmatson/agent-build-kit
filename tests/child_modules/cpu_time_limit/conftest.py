from collections.abc import Callable

import pytest

from tests.cpu_spin import busy_cpu, make_backstop_unreachable

make_backstop_unreachable()


@pytest.fixture(scope="session")
def spin_cpu() -> Callable[[float], None]:
    """Spins until the process has used that much CPU."""
    return busy_cpu
