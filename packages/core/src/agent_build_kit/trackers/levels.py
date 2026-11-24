"""Which board items a merged unit's pull request attaches to, from the levels in use."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def group_key(change: str, group: int) -> str:
    """The item key of a group: `<change>:<group>`."""
    return f"{change}:{group}"


def task_key(change: str, group: int, number: int) -> str:
    """The item key of a task: `<change>:<group>.<task>`."""
    return f"{group_key(change, group)}.{number}"


def task_group_key(key: str) -> str:
    """The group key of a task key made by `task_key`."""
    return key.rsplit(".", 1)[0]


def link_targets(
    levels: Sequence[str],
    pr_links: str | Sequence[str],
    change: str,
    built: Mapping[int, Sequence[int]],
) -> tuple[str, ...]:
    """The item keys that get the pull request of a unit that built `built` (group number to the
    numbers of its tasks) in `change`: `<change>`, `<change>:<group>` and `<change>:<group>.<task>`.
    The manual epic is never a target."""
    if pr_links == "lowest":
        wanted = [levels[-1]]
    elif pr_links == "all":
        wanted = list(levels)
    else:
        wanted = [entity for entity in levels if entity in pr_links]
    keys: list[str] = [change] if "change" in wanted else []
    for group, tasks in sorted(built.items()):
        if "group" in wanted:
            keys.append(group_key(change, group))
        if "task" in wanted:
            keys.extend(task_key(change, group, task) for task in tasks)
    return tuple(keys)
