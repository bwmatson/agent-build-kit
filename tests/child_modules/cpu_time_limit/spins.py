from collections.abc import Callable


def test_spins_in_its_own_process(spin_cpu: Callable[[float], None]) -> None:
    spin_cpu(30)
