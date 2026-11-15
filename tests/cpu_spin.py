"""What the child scenarios of the time-limit plugin share: a spin counted in CPU. A scenario that
wants the wall backstop out of reach, so a CPU-bound test meets its CPU budget at any machine
load, sets `time_limit_backstop_factor` in its `pytest.ini`."""

from __future__ import annotations

import time


def busy_cpu(seconds: float) -> None:
    """Spin until the process has used that much CPU."""
    deadline = time.process_time() + seconds
    while time.process_time() < deadline:
        pass
