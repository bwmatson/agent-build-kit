"""What the Azure DevOps doctor probe says about a project, one line for each check."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

from pydantic import BaseModel

from agent_build_kit.forges.transport import AuthError, AzureRest, NotFound, validated
from agent_build_kit.trackers.azure_work_item_models import BacklogsDoc, WorkItemTypesDoc
from agent_build_kit.trackers.base import Identity, ProbeLine
from agent_build_kit.trackers.config import AzureDevOpsTracker

# The kit's states, whose mapping onto each type's states is checked.
KIT_STATES = ("new", "active", "done", "removed")


def probe(
    section: AzureDevOpsTracker, rest: AzureRest, identity: Callable[[], Identity]
) -> list[ProbeLine]:
    """Who the credential is, then each check against the project's real types, states, backlog
    levels, team and paths. A credential without work item scope ends it at one line."""
    lines: list[ProbeLine] = []
    try:
        lines.append(ProbeLine(ok=True, text=f"credential: {identity().name}"))
    except Exception as error:  # the host answers in its own errors; all mean no identity
        lines.append(ProbeLine(ok=False, text=f"credential: the host gave no identity ({error})"))
    organization, project = section.organization, section.project

    def read[Doc: BaseModel](model: type[Doc], path: str, within: str = project) -> Doc:
        response = rest.call(organization, within, "GET", path)
        return validated(model, response.data, path, response.text)

    try:
        types = {
            found.name: tuple(state.name for state in found.states)
            for found in read(WorkItemTypesDoc, "wit/workitemtypes").value
        }
    except AuthError:
        lines.append(
            ProbeLine(
                ok=False,
                text="work item access: the credential cannot read work items; "
                "give it the work item (read) scope",
            )
        )
        return lines
    lines.append(ProbeLine(ok=True, text="work item access: the credential can read work items"))
    lines += _types(section, types)
    lines += _states(section, types)
    team = section.team
    try:
        backlogs = read(BacklogsDoc, "work/backlogs", f"{project}/{quote(team)}")
    except NotFound:
        lines.append(ProbeLine(ok=False, text=f"team: {team} does not exist in {project}"))
    else:
        lines.append(ProbeLine(ok=True, text=f"team: {team} exists"))
        # The list's order says nothing; the rank does, the highest being the top level.
        ranked = sorted(backlogs.value, key=lambda level: level.rank, reverse=True)
        levels = [tuple(t.name for t in level.work_item_types) for level in ranked]
        lines += _nesting(section, types, levels)
    for tree, label, path in (
        ("areas", "area path", section.area_path),
        ("iterations", "iteration path", section.iteration_path),
    ):
        below_root = "/".join(path.split("\\")[1:])
        try:
            if below_root:
                rest.call(
                    organization, project, "GET", f"wit/classificationnodes/{tree}/{below_root}"
                )
        except NotFound:
            lines.append(ProbeLine(ok=False, text=f"{label}: {path} does not exist"))
        else:
            lines.append(ProbeLine(ok=True, text=f"{label}: {path} exists"))
    return lines


def _types(section: AzureDevOpsTracker, types: dict[str, tuple[str, ...]]) -> list[ProbeLine]:
    wanted = {level: section.level_types[level] for level in section.levels}
    missing = [
        ProbeLine(
            ok=False, text=f"types: level {level} uses type {name}, which the project does not have"
        )
        for level, name in wanted.items()
        if name not in types
    ]
    return missing or [ProbeLine(ok=True, text=f"types: {', '.join(wanted.values())} exist")]


def _states(section: AzureDevOpsTracker, types: dict[str, tuple[str, ...]]) -> list[ProbeLine]:
    lines: list[ProbeLine] = []
    for level in section.levels:
        name = section.level_types[level]
        for state in KIT_STATES if name in types else ():
            try:
                board = section.board_state(name, state)
            except ValueError:  # the process names no board state for it
                if state != "removed":  # the kit moves an item through the other three
                    lines.append(
                        ProbeLine(
                            ok=False,
                            text=f"states: type {name} has no board state for the kit's {state}; "
                            "map it in `states` or `states_by_type`",
                        )
                    )
                continue
            if board not in types[name]:
                lines.append(
                    ProbeLine(
                        ok=False,
                        text=f"states: {board} (the kit's {state}) is not a state of type {name}",
                    )
                )
    return lines or [ProbeLine(ok=True, text="states: every mapped state exists for its type")]


def _nesting(
    section: AzureDevOpsTracker, types: dict[str, tuple[str, ...]], backlogs: list[tuple[str, ...]]
) -> list[ProbeLine]:
    """The epic must sit on a level above the first level's type, and each level's type on a
    level below the one above it. `backlogs` is top level first. A type the project has but no
    backlog level holds cannot be nested, so it is said (one the project lacks is said by the
    types line)."""
    level_of = {name: position for position, names in enumerate(backlogs) for name in names}
    chain = [section.level_types[level] for level in section.levels]
    lines: list[ProbeLine] = []
    if section.epic:
        epic = section.level_types["epic"]
        if epic in level_of and chain[0] in level_of and level_of[epic] < level_of[chain[0]]:
            lines.append(ProbeLine(ok=True, text=f"epic: {epic} sits above {chain[0]}"))
        else:
            lines.append(
                ProbeLine(
                    ok=False,
                    text=f"epic: type {epic} does not exist above the first level ({chain[0]})",
                )
            )
    unplaced = [
        ProbeLine(ok=False, text=f"nesting: level {level}'s type {name} is on no backlog level")
        for level, name in zip(section.levels, chain, strict=True)
        if name in types and name not in level_of
    ]
    refused = [
        ProbeLine(
            ok=False,
            text=f"nesting: {below} under {above} is not allowed in this project's backlog levels",
        )
        for above, below in zip(chain, chain[1:], strict=False)
        if above in level_of and below in level_of and level_of[below] <= level_of[above]
    ]
    return [
        *lines,
        *unplaced,
        *(refused or [ProbeLine(ok=True, text="nesting: each level fits under the one above")]),
    ]
