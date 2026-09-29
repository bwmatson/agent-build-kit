"""Whether the active runtime refuses what abk forbids, asked at most once a
short while.

`check_policy` may cost an agent call (a probe run), and `doctor` and `init`
ask it every time they run, so an answer is kept in a file beside the usage
reading and reused while it is fresh. A caller that has just changed what the
answer depends on — `init`, after running the installation's fix — asks for a
fresh one.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from agent_build_kit.runtimes.base import AgentRuntime, PolicyReport

# How long an answer is reused before the runtime is asked again.
MAX_AGE = timedelta(minutes=15)


def checked(
    runtime: AgentRuntime,
    cwd: Path,
    *,
    cache: Path,
    now: datetime | None = None,
    fresh: bool = False,
) -> PolicyReport:
    """`runtime.check_policy(cwd)`, or the answer it gave within `MAX_AGE`."""
    raise NotImplementedError
