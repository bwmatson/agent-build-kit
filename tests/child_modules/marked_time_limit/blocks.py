import threading

import pytest


@pytest.mark.time_limit(1)
def test_marked_runs_past_its_own_limit() -> None:
    threading.Event().wait()


def test_unmarked_beside_them() -> None:
    threading.Event().wait()
