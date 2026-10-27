"""What `abk doctor` and `abk status` say about a repo's tracker; nothing for a repo without one."""

from __future__ import annotations

from typing import Literal

from agent_build_kit import trackers
from agent_build_kit.model import Frozen
from agent_build_kit.trackers.config import TrackerConfigError, section_for


class Standing(Frozen):
    """One repo's tracker: its target, and whether the section is usable and the credential
    accepted. `identity` is only asked of the host when `ask` is set."""

    repo: str
    state: Literal["ok", "refused", "invalid"]
    text: str


def standing(repo: str, *, ask: bool) -> Standing | None:
    """None when the repo has no tracker section."""
    try:
        section = section_for(repo)
        if section is None:
            return None
        tracker = trackers.for_repo(repo) if ask else None
    except TrackerConfigError as error:
        return Standing(repo=repo, state="invalid", text=str(error))
    if tracker is None:
        return Standing(repo=repo, state="ok", text=section.target)
    try:
        who = tracker.identity().name
    except Exception as error:  # the host answers in its own errors; all mean it did not accept us
        return Standing(repo=repo, state="refused", text=f"{section.target}: {error}")
    return Standing(repo=repo, state="ok", text=f"{section.target} as {who}")
