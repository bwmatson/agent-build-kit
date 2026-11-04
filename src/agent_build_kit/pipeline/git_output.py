"""What git's output means: the one place it is read.

A push's outcome and rerere's replay notice are decisions that can only come
from git's own text. Callers use the typed result here and never read it again.
"""

import os
import re
import subprocess
from typing import Literal

from agent_build_kit.model import Frozen

# What a refused push says it was, in the `HostUnavailable` it is raised as: the forge's resilient
# wrapper raises the same error for its API calls, under the name of the call.
PUSH_OPERATION = "git push"

# `host_refused` and `host_unreachable` are an outage of the code host (see `transport_failure`),
# not an answer about the branch.
PushKind = Literal["stale_lease", "rejected_by_remote", "host_refused", "host_unreachable", "other"]

# What a failed push, fetch or ls-remote says about the host: it refused the call, or it was
# not reached at all.
TransportKind = Literal["refused", "unreachable"]


class PushResult(Frozen):
    """How a failed `git push --porcelain` ended, and what the remote said about it."""

    kind: PushKind
    message: str = ""


class TransportFailure(Frozen):
    """A failed push, fetch or ls-remote that is an outage of the host, and what git said."""

    kind: TransportKind
    message: str


class FetchFailed(RuntimeError):
    """A fetch that failed. `failure` is set when the host refused it or could not be reached."""

    def __init__(self, message: str, failure: TransportFailure | None) -> None:
        super().__init__(message)
        self.failure = failure


REPLAYED_NOTICE = re.compile(r"^Resolved '(.+)' using previous resolution\.$", re.MULTILINE)

# A porcelain push prints one `<flag>\t<from>:<to>\t<summary> (<reason>)` line per ref;
# `!` is a ref that was refused.
REFUSED_REF = re.compile(r"^!\t[^\t]*\t\[(?P<what>[^\]]+)\](?: \((?P<why>.*)\))?$", re.MULTILINE)


# The host answered about the repository or the person, which only a person can put right: a
# repository the account may not read or write, or one that is not there. Never an outage, and
# checked before the HTTP statuses it arrives with (GitHub answers these with a 403).
REPO_ACCESS = re.compile(
    r"Permission to \S+ denied to"
    r"|Write access to repository not granted"
    r"|Repository not found"
)

# The host answered and said no: a refused key or login, an HTTP error status from the remote, a
# connection it closed on us. Fixed-locale text only: callers run git with `untranslated_env()`.
HOST_REFUSED = re.compile(
    r"Permission denied \(publickey"
    r"|Authentication failed"
    r"|The requested URL returned error: (?:401|403|5\d\d)\b"
    r"|Connection closed by (?:remote host|\S+ port \d+)"
    r"|[sk]?ssh_exchange_identification|kex_exchange_identification"
)

# The call never got an answer: the name did not resolve, or the connect failed.
HOST_UNREACHABLE = re.compile(
    r"Could not resolve host"
    r"|Temporary failure in name resolution"
    r"|Connection (?:timed out|refused|reset)"
    r"|Network is unreachable"
    r"|Failed to connect to \S+ port \d+"
)


def transport_failure(output: str) -> TransportFailure | None:
    """Whether the output of a failed `git push`, `git fetch` or `git ls-remote` is an outage of
    the host, and which kind; None for any other failure.

    A refusal is checked first, since a refused connection can follow it in the same output.
    The caller has already ruled out a ref the remote rejected, which is its answer about the
    branch and never an outage.
    """
    message = output.strip()
    if REPO_ACCESS.search(message):
        return None
    if HOST_REFUSED.search(message):
        return TransportFailure(kind="refused", message=message)
    if HOST_UNREACHABLE.search(message):
        return TransportFailure(kind="unreachable", message=message)
    return None


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
    non-fast-forward are the remote's answer. Of the rest, a host that refused the call or
    could not be reached is an outage (`host_refused`, `host_unreachable`), and anything else
    is another failure.
    """
    message = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part)
    kind: PushKind = "other"
    for refused in REFUSED_REF.finditer(result.stdout):
        what, why = refused["what"], refused["why"] or ""
        if what == "rejected" and why == "stale info":
            return PushResult(kind="stale_lease", message=message)
        kind = "rejected_by_remote"
    if kind == "other" and (failure := transport_failure(message)):
        kind = "host_refused" if failure.kind == "refused" else "host_unreachable"
    return PushResult(kind=kind, message=message)


def replayed_files(output: str) -> list[str]:
    """The paths rerere's replay notice names in `output` of a rebase."""
    return REPLAYED_NOTICE.findall(output)
