"""What `abk doctor` and `abk status` say about a repo's tracker; nothing for a repo without one."""

from __future__ import annotations

from typing import Literal

from agent_build_kit import trackers
from agent_build_kit.model import Frozen
from agent_build_kit.trackers.config import TrackerConfigError, section_for


class Standing(Frozen):
    """One repo's tracker. `invalid`: the section is wrong. `unsupported`: the section is valid
    but this kit has no implementation of its kind. `refused`: the host did not accept the
    identity check. `token_env` is the section's credential variable, when it names one."""

    repo: str
    state: Literal["ok", "refused", "invalid", "unsupported"]
    text: str
    kind: str = ""
    token_env: str | None = None


def standing(repo: str, *, ask: bool) -> Standing | None:
    """None when the repo has no tracker section. The host is asked who the credential is only
    when `ask` is set."""
    try:
        section = section_for(repo)
    except TrackerConfigError as error:
        return Standing(repo=repo, state="invalid", text=str(error))
    if section is None:
        return None
    known = {"repo": repo, "kind": section.kind, "token_env": section.token_env}
    if not ask:
        return Standing(state="ok", text=section.target, **known)
    try:
        tracker = trackers.for_repo(repo)
    except TrackerConfigError as error:  # the section is valid, so no factory is registered
        return Standing(state="unsupported", text=f"{section.target}: {error}", **known)
    if tracker is None:
        return None
    try:
        who = tracker.identity().name
    except Exception as error:  # the host answers in its own errors; all mean no identity
        return Standing(state="refused", text=f"{section.target}: {error}", **known)
    return Standing(state="ok", text=f"{section.target} as {who}", **known)
