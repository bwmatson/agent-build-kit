import time


def test_spins_in_its_own_process() -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        pass
