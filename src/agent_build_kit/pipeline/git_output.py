"""What git's output means: the one place it is read.

A push's outcome and rerere's replay notice are decisions that can only come
from git's own text. Callers use the typed result here and never read it again.
"""

import os
import re
import subprocess
from typing import Literal

from agent_build_kit.model import Frozen

PushKind = Literal["stale_lease", "rejected_by_remote", "other"]


class PushResult(Frozen):
    """How a failed `git push --porcelain` ended, and what the remote said about it."""

    kind: PushKind
    message: str = ""


REPLAYED_NOTICE = re.compile(r"^Resolved '(.+)' using previous resolution\.$", re.MULTILINE)

# A porcelain push prints one `<flag>\t<from>:<to>\t<summary> (<reason>)` line per ref;
# `!` is a ref that was refused.
REFUSED_REF = re.compile(r"^!\t[^\t]*\t\[(?P<what>[^\]]+)\](?: \((?P<why>.*)\))?$", re.MULTILINE)


def untranslated_env() -> dict[str, str]:
    """The environment for a git call whose output is read.

    Git's messages go through gettext, so a translated locale would break every
    match here. Built at call time, not import, so it follows the live environment.
    """
    return {**os.environ, "LC_ALL": "C", "LANGUAGE": "C"}


def git_push_outcome(result: subprocess.CompletedProcess[str]) -> PushResult:
    """Classify a failed `git push --porcelain` run with a fixed locale.

    Only a refused ref reported as `[rejected] (stale info)` is a lease that no
    longer holds; a remote's refusal (a hook, branch protection) and a
    non-fast-forward are the remote's answer, and anything else is another failure.
    """
    message = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part)
    kind: PushKind = "other"
    for refused in REFUSED_REF.finditer(result.stdout):
        what, why = refused["what"], refused["why"] or ""
        if what == "rejected" and why == "stale info":
            return PushResult(kind="stale_lease", message=message)
        kind = "rejected_by_remote"
    return PushResult(kind=kind, message=message)


def replayed_files(output: str) -> list[str]:
    """The paths rerere's replay notice names in `output` of a rebase."""
    return REPLAYED_NOTICE.findall(output)
