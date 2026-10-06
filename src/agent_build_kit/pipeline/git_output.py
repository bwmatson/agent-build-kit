"""What git's output means: the one place it is read.

A push's outcome and rerere's replay notice are decisions that can only come
from git's own text. Callers use the typed result here and never read it again.
"""

import subprocess
from typing import Literal

from agent_build_kit.model import Frozen

PushKind = Literal["stale_lease", "rejected_by_remote", "other"]


class PushResult(Frozen):
    """How a failed `git push --porcelain` ended, and what the remote said about it."""

    kind: PushKind
    message: str = ""


def git_push_outcome(result: subprocess.CompletedProcess[str]) -> PushResult:
    raise NotImplementedError


def replayed_files(output: str) -> list[str]:
    """The paths rerere's replay notice names in `output` of a rebase."""
    raise NotImplementedError
