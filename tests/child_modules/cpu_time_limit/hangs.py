from collections.abc import Callable


def test_hangs(spin_cpu: Callable[[float], None]) -> None:
    spin_cpu(20)


def test_after_it() -> None:
    pass
