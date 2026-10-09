"""What a commit of the planning checkout means for the units of its change that have started.

Listed for the person, never acted on: a `Needs:` edit is applied by the next tick, a plan
change is re-planned by it with built units keeping their state, and a requirement a started
unit built to may no longer match its branch, which only a rework or a requeue settles.
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.shell import git_out
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, RUNNING

STARTED = frozenset({RUNNING, IN_REVIEW, HELD, FAILED})
_GROUP = re.compile(r"^## (\d+)\.", re.MULTILINE)
_NEEDS = re.compile(r"^Needs:", re.IGNORECASE)


class Consequence(Frozen):
    kind: str  # needs | replan | spec
    units: tuple[str, ...]
    message: str


def _groups(text: str) -> dict[str, tuple[frozenset[str], tuple[str, ...]]]:
    """Each task group's `Needs:` lines and every other line of it."""
    marks = list(_GROUP.finditer(text))
    found: dict[str, tuple[frozenset[str], tuple[str, ...]]] = {}
    for at, mark in enumerate(marks):
        end = marks[at + 1].start() if at + 1 < len(marks) else len(text)
        body = text[mark.start() : end].splitlines()
        needs = frozenset(line.strip() for line in body if _NEEDS.match(line.strip()))
        rest = tuple(line.rstrip() for line in body if line.strip() and not _NEEDS.match(line))
        found[mark.group(1)] = (needs, rest)
    return found


def _show(root: Path, ref: str, path: str) -> str:
    try:
        return git_out(root, "show", f"{ref}:{path}")
    except Exception:  # noqa: BLE001 — absent in that commit
        return ""


def consequences_of(
    inst: Installation, change: str, before: str, after: str, *, store: UnitStore
) -> list[Consequence]:
    """The consequences of the planning commit `before..after` for `change`'s started units."""
    root = inst.root
    prefix = f"{inst.changes_dir.relative_to(inst.root).as_posix()}/{change}/"
    touched = git_out(root, "diff", "--name-only", before, after).splitlines()
    started = [u for u in store.all() if u.change == change and u.branch and u.state in STARTED]
    ids = tuple(u.id for u in started)
    listed: list[Consequence] = []
    tasks = f"{prefix}tasks.md"
    if tasks in touched and ids:
        old, new = _groups(_show(root, before, tasks)), _groups(_show(root, after, tasks))
        replanned = old.keys() != new.keys() or any(old[n][1] != new[n][1] for n in old if n in new)
        if replanned:
            listed.append(
                Consequence(
                    kind="replan",
                    units=ids,
                    message="The plan changed: the change is re-planned on the next tick, "
                    "and built units keep their state.",
                )
            )
        else:
            moved = {n for n in old if old[n][0] != new[n][0]}
            hit = tuple(u.id for u in started if _number(u) in moved)
            if hit:
                listed.append(
                    Consequence(
                        kind="needs",
                        units=hit,
                        message="Only a `Needs:` line changed: the gate applies on the next tick.",
                    )
                )
    if any(p.startswith(f"{prefix}specs/") for p in touched) and ids:
        listed.append(
            Consequence(
                kind="spec",
                units=ids,
                message="A requirement the unit was built to changed, so its branch may no "
                "longer match the spec. It is flagged for a rework or a requeue; nothing about "
                "it is changed automatically.",
            )
        )
    return listed


def _number(unit: StoredUnit) -> str:
    return unit.id.rsplit("/", 1)[-1]
