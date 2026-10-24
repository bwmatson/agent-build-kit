"""Which check a failed unit-test run was (spec: telemetry).

The metrics count a failure by its kind, never by its text, and three kinds
cover what a person acts on: the linter or formatter (`lint`), the type
checker (`types`), the tests (`test`). Which tool means which, and what its
output looks like, is the toolchain profile's to say; this only asks it.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import RepoConfig, active, owning_project

_IN = re.compile(r"\(in (?P<dir>.+)\)")
KINDS = ("lint", "types", "test")

_SERVICE_TARGET = re.compile(
    # `::1` alone or with a port (`::1:5432`), never the tail of a longer address.
    r"\b127\.\d+\.\d+\.\d+|\blocalhost\b|(?<![0-9a-f:])::1(?![0-9a-f]|:[0-9a-f]*[a-f:])|\.sock\b"
    r"|Connection aborted",
    re.I,
)
# The phrases of strerror (Python, C) and the errno names (node and others).
_REFUSED = re.compile(
    r"permission denied|operation not permitted|connection refused"
    r"|\b(?:EACCES|EPERM|ECONNREFUSED)\b",
    re.I,
)
# A refusal and the target it names belong to one failure, so they sit this close together.
_NEAR = 3

E2E_HINT = (
    "A step that needs a running service is an e2e test: a unit-test step cannot reach "
    "localhost or a service socket. Move the test to the e2e tests and tag its group "
    "`[e2e-test]` instead of working around the refusal."
)


def with_e2e_hint(output: str) -> str:
    """`output` of a failed unit-test run, with the e2e hint added when it shows a refused
    loopback connection or service socket: a refusal within a few lines of the target."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if _REFUSED.search(line):
            near = "\n".join(lines[max(0, i - _NEAR) : i + _NEAR + 1])
            if _SERVICE_TARGET.search(near):
                return f"{output.rstrip()}\n\n{E2E_HINT}"
    return output


def failed_in(where: Path) -> str:
    """The line of a failure that names the project directory its command ran in."""
    return f"(in {where})"


def failed_dir(output: str) -> str | None:
    """The directory `failed_in` named under a failed command's header; None when there is none."""
    lines = output.lstrip().splitlines()
    found = _IN.fullmatch(lines[1]) if len(lines) > 1 else None
    return found["dir"] if found else None


def failed_check(output: str, repo: str | None = None) -> str:
    """`lint`, `types` or `test`: what failed in `output`, a unit-test failure of
    `repo`. The profile of the project the failed command ran in reads it (unit-test names
    that directory under the command); the repo's profile otherwise, and the default
    profile when `repo` is unnamed."""
    entry = active().repos.get(repo) if repo else None
    return profiles.get(_profile_of(output, entry)).failure_kind(output)


def _profile_of(output: str, entry: RepoConfig | None) -> str:
    if entry is None:
        return "python-uv"
    where = failed_dir(output)
    if where is not None:
        # The directory is the checkout's path to the project, so the project's whole path is
        # a tail of it; a longer tail is a deeper project. A directory above the checkout
        # that shares a project's name is not the project, and the checkout itself is the
        # root project's. The one case this misreads is a checkout whose own directory is
        # named like one of its projects' paths.
        by_path = {p.path: p for p in entry.projects}
        parts = Path(where).parts
        for k in range(len(parts)):
            owner = by_path.get("/".join(parts[k:]))
            if owner is not None:
                return owner.profile
        root = owning_project(entry.projects, "")
        if root is not None:
            return root.profile
    return entry.profile
