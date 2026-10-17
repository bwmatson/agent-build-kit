"""A pytest plugin that prints a scratch installation's state with a failed live test.

For a `local_stack` test whose setup, call or teardown failed and that has a scratch (a fixture
argument named `scratch`, or one passed to `register_scratch` during the test), a section named
`SCRATCH STATE` is added to the report, last in the test's failure block. It opens with a
`cause hints:` line and holds the sources of the design, each within its cap, redacted. Git runs
as `runner.run(argv, timeout=GIT_TIMEOUT, ...)` and the redactor is `redactor.redact_text`; a test
replaces either with a stand-in. A source that cannot be read becomes one line,
`scratch state unavailable: <ExceptionType>`, and never changes the test's outcome.
"""

from __future__ import annotations

import subprocess

from agent_build_kit import redaction
from tests.scratch_tick import Scratch, TickResult

# Seconds each `git` command may take.
GIT_TIMEOUT = 10

# The most characters one dump holds, and all the dumps of one session.
DUMP_CHARS = 20480
SESSION_CHARS = 61440

runner = subprocess
redactor = redaction


def cause_hints(scratch: Scratch, branch: str | None = None, tick: TickResult | None = None) -> str:
    """The `cause hints: ...` line: the last tick's return code, the pause marker, whether
    `branch` is on the remote, the unit's wait reason. The guarded branch check opens with it."""
    raise NotImplementedError


def scratch_state(scratch: Scratch) -> str:
    """The text of the `SCRATCH STATE` section for `scratch`, redacted and within its caps."""
    raise NotImplementedError
