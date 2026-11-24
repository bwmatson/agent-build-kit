"""What `abk doctor` and `abk status` say about a repo's tracker; nothing for a repo without one."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from agent_build_kit import trackers
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.tracker_file import read_tracker
from agent_build_kit.trackers.base import ProbeLine
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


def probe_lines(repo: str) -> list[ProbeLine]:
    """What the repo's tracker says about its project, one line for each check; none for a
    tracker with no probe (it is not part of the `Tracker` protocol) or no tracker at all."""
    try:
        tracker = trackers.for_repo(repo)
    except TrackerConfigError:
        return []
    if tracker is None or not hasattr(tracker, "probe"):
        return []
    try:
        return list(tracker.probe())
    except Exception as error:  # the host answers in its own errors
        return [ProbeLine(ok=False, text=f"probe: the host could not be read ({error})")]


def conflict_lines(changes_dir: Path) -> list[str]:
    """One line for each conflict a change's tracker file records as open (the change, the item
    and field, and both values) and for each change whose manual epic was closed or removed."""
    lines: list[str] = []
    for folder in sorted(changes_dir.glob("*/tracker.yaml")):
        try:
            recorded = read_tracker(folder.parent)
        except (OSError, ValueError):
            continue
        if recorded is not None and recorded.epic_warned:
            lines.append(
                f"tracker epic: {folder.parent.name} epic {recorded.epic} was closed or removed"
            )
        for record in recorded.conflicts if recorded else ():
            if record.status == "open":
                lines.append(
                    f"tracker conflict: {folder.parent.name} item {record.item_id} "
                    f"{record.field}: spec {record.spec_value!r}, board {record.tracker_value!r}"
                )
    return lines
