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
from agent_build_kit.pipeline.work_graph import specification_text

STARTED = frozenset({RUNNING, IN_REVIEW, HELD, FAILED})
_GROUP = re.compile(r"^## (\d+)\.", re.MULTILINE)
_NEEDS = re.compile(r"^Needs:", re.IGNORECASE)


class Consequence(Frozen):
    kind: str  # needs | replan | spec
    units: tuple[str, ...]
    message: str


def _needs(text: str) -> dict[int, frozenset[str]]:
    """Each task group's `Needs:` lines."""
    marks = list(_GROUP.finditer(text))
    found: dict[int, frozenset[str]] = {}
    for at, mark in enumerate(marks):
        end = marks[at + 1].start() if at + 1 < len(marks) else len(text)
        body = text[mark.start() : end].splitlines()
        found[int(mark.group(1))] = frozenset(
            line.strip() for line in body if _NEEDS.match(line.strip())
        )
    return found


def _builds(unit: StoredUnit, change: str) -> frozenset[int]:
    """The groups of `change` that `unit` builds, its own or carried."""
    return frozenset(g for m in unit.members() if m.change == change for g in m.groups)


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
    started = [
        u
        for u in store.all()
        if u.branch and u.state in STARTED and any(m.change == change for m in u.members())
    ]
    ids = tuple(u.id for u in started)
    listed: list[Consequence] = []
    tasks = f"{prefix}tasks.md"
    if tasks in touched and ids:
        old, new = _show(root, before, tasks), _show(root, after, tasks)
        if specification_text(old) != specification_text(new):
            listed.append(
                Consequence(
                    kind="replan",
                    units=ids,
                    message="The plan changed: the change is re-planned on the next tick, "
                    "and built units keep their state.",
                )
            )
        else:
            was, now = _needs(old), _needs(new)
            moved = {n for n in was.keys() | now.keys() if was.get(n) != now.get(n)}
            hit = tuple(u.id for u in started if _builds(u, change) & moved)
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
