"""What the child scenarios of the time-limit plugin share: a spin counted in CPU, and a wall
backstop out of reach, so a CPU-bound test meets its CPU budget at any machine load."""

from __future__ import annotations

import time

import tests.time_limit

UNREACHABLE_BACKSTOP_FACTOR = 10_000


def busy_cpu(seconds: float) -> None:
    """Spin until the process has used that much CPU."""
    deadline = time.process_time() + seconds
    while time.process_time() < deadline:
        pass


def make_backstop_unreachable() -> None:
    tests.time_limit.BACKSTOP_FACTOR = UNREACHABLE_BACKSTOP_FACTOR
