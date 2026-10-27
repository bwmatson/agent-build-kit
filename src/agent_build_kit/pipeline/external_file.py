"""The hold file of a change: work handed to someone outside the kit (spec: external-work).

`external.yaml` in a change's folder records holds on the whole change or on named groups. The
kit never starts a unit whose groups are all held. The file is read by the planner and the start
path, is not part of the plan hash, and is written only here, under a lock and whole.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

import yaml
from pydantic import Field

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.units import BUILDS_NOTHING, PLANNED, Unit, is_superseded
from agent_build_kit.pipeline.work_graph import GROUP_NUMBER

if TYPE_CHECKING:
    from agent_build_kit.pipeline.unit_store import StoredUnit

FILE_NAME = "external.yaml"
HELD = "held"
DONE = "done"
RELEASED = "released"

# `all` covers every group of the change's `tasks.md`, those added later too. A list of groups
# names at least one.
Scope = Literal["all"] | Annotated[tuple[int, ...], Field(min_length=1)]


class HoldRefused(ValueError):
    """A hold that cannot be recorded; the message says why."""


class Hold(Frozen):
    """Work handed to `holder`. A status other than the ones above was written by a later
    release and keeps its groups blocked; so does a hold with a field this release does not
    know, which the reader leaves out."""

    scope: Scope
    holder: str
    link: str
    since: datetime
    items: dict[str, str | list[str]] = {}
    note: str = ""
    status: str = HELD
    merged_by: str = ""
    done_at: datetime | None = None


def external_path(change_dir: Path) -> Path:
    """Where `change_dir` keeps its holds."""
    return change_dir / FILE_NAME


def read_holds(change_dir: Path) -> tuple[Hold, ...]:
    """The holds of a change, none when it has no file. The file is replaced whole, so a read
    needs no lock."""
    path = external_path(change_dir)
    if not path.is_file():
        return ()
    loaded = yaml.safe_load(path.read_text()) or {}
    known = Hold.model_fields.keys()
    return tuple(
        Hold.model_validate({key: value for key, value in raw.items() if key in known})
        for raw in loaded.get("holds", ())
    )


def _lock(path: Path) -> Path:
    return path.with_name(f"{path.name}.lock")


def _write(path: Path, holds: Sequence[Hold]) -> None:
    """Replace the file whole or not at all; the caller holds the lock."""
    listed = [hold.model_dump(mode="json") for hold in holds]
    atomic_write_text(path, yaml.safe_dump({"holds": listed}, sort_keys=False))


def write_holds(change_dir: Path, holds: Sequence[Hold]) -> None:
    """Replace the file's holds, under the file's lock."""
    path = external_path(change_dir)
    with file_lock(_lock(path)):
        _write(path, holds)


def _group_numbers(change_dir: Path) -> tuple[int, ...]:
    tasks = change_dir / "tasks.md"
    if not tasks.is_file():
        return ()
    found = (GROUP_NUMBER.match(line) for line in tasks.read_text().splitlines())
    return tuple(int(match["number"]) for match in found if match)


def _covered(hold: Hold, existing: Sequence[int]) -> frozenset[int]:
    return frozenset(existing) if hold.scope == "all" else frozenset(hold.scope)


def _coverage(change_dir: Path, holds: Sequence[Hold]) -> list[tuple[Hold, frozenset[int]]]:
    """Each hold with the groups it covers. A hold on `all` leaves out the groups a done hold
    of the file has taken, so what it still holds grows with the change's groups."""
    existing = _group_numbers(change_dir)
    taken = frozenset(
        number for hold in holds if hold.status == DONE for number in _covered(hold, existing)
    )
    return [
        (hold, _covered(hold, existing) - (taken if hold.scope == "all" else frozenset()))
        for hold in holds
    ]


def add_hold(change_dir: Path, hold: Hold) -> None:
    """Record `hold`; raises `HoldRefused` for a group the change lacks or one already held.
    The checks and the write are one step under the file's lock."""
    path = external_path(change_dir)
    with file_lock(_lock(path)):
        existing = _group_numbers(change_dir)
        covered = _covered(hold, existing)
        for number in sorted(covered - set(existing)):
            raise HoldRefused(f"group {number} does not exist in change {change_dir.name}")
        holds = read_holds(change_dir)
        for other, others in _coverage(change_dir, holds):
            if other.status == RELEASED:
                continue
            for number in sorted(covered & others):
                raise HoldRefused(
                    f"group {number} of change {change_dir.name} is already held by {other.holder}"
                )
        _write(path, [*holds, hold])


def already_held(change_dir: Path, hold: Hold) -> bool:
    """Whether the holds of `hold`'s holder that are still held already cover everything `hold`
    asks for, so recording it again would change nothing. `all` is covered only by an `all`."""
    mine = [
        (other, groups)
        for other, groups in _coverage(change_dir, read_holds(change_dir))
        if other.status == HELD and other.holder == hold.holder
    ]
    if hold.scope == "all":
        return any(other.scope == "all" for other, _ in mine)
    return set(hold.scope) <= set().union(*(groups for _, groups in mine))


def _holding(change_dir: Path, *, recorded: bool = False) -> dict[int, Hold]:
    """Each group the kit must leave alone, with the hold that has it: those of every hold
    neither done nor released, and with `recorded` those done by hand too."""
    holding: dict[int, Hold] = {}
    for hold, groups in _coverage(change_dir, read_holds(change_dir)):
        if hold.status != RELEASED and (recorded or hold.status != DONE):
            holding.update({number: hold for number in groups})
    return holding


def blocked_groups(change_dir: Path) -> frozenset[int]:
    """The groups the kit must leave alone: those of every hold neither done nor released."""
    return frozenset(_holding(change_dir))


def done_groups(change_dir: Path) -> frozenset[int]:
    """The groups whose hand merge has been recorded."""
    return frozenset(
        number
        for hold, groups in _coverage(change_dir, read_holds(change_dir))
        if hold.status == DONE
        for number in groups
    )


def held_units(changes_dir: Path, units: Sequence[Unit]) -> dict[str, Hold]:
    """The planned units whose groups are all held, or done by hand while another group of the
    unit is still held, each with the first hold still held."""
    holding: dict[str, dict[int, Hold]] = {}
    found: dict[str, Hold] = {}
    for unit in units:
        if unit.state != PLANNED:
            continue
        holds = [
            holding.setdefault(
                member.change, _holding(changes_dir / member.change, recorded=True)
            ).get(number)
            for member in unit.members()
            for number in member.groups
        ]
        live = [found_hold for found_hold in holds if found_hold and found_hold.status != DONE]
        if holds and all(holds) and live:
            found[unit.id] = live[0]
    return found


def external_reason(hold: Hold) -> str:
    """What a unit held by `hold` reads in words."""
    return f"held externally by {hold.holder}: {hold.link}"


def check_not_started(change_dir: Path, hold: Hold, units: Sequence[StoredUnit]) -> None:
    """Raise `HoldRefused` when a unit that has started carries a group `hold` covers."""
    covered = _covered(hold, _group_numbers(change_dir))
    for unit in units:
        # A retired or unplanned unit builds nothing, and a replaced one is carried by its
        # successors: neither holds its groups.
        if unit.state in BUILDS_NOTHING or is_superseded(unit):
            continue
        mine = {
            n
            for member in unit.members()
            if member.change == change_dir.name
            for n in member.groups
        }
        if not covered & mine:
            continue
        if unit.state == PLANNED and not (unit.pr or unit.branch or unit.pushed or unit.approved):
            continue
        raise HoldRefused(
            f"unit {unit.id} ({unit.state.value}) has already started group "
            f"{min(covered & mine)} of change {change_dir.name}: let it finish, or retire it "
            "first, which returns its groups to the plan"
        )


def release_holds(change_dir: Path, groups: Sequence[int]) -> tuple[int, ...]:
    """Give back the work of every hold that has one of `groups`, in one step under the lock, and
    return every group those holds covered. Raises `HoldRefused`, writing nothing, when a group
    is held by none or its hold is done."""
    path = external_path(change_dir)
    with file_lock(_lock(path)):
        holds = read_holds(change_dir)
        out = list(holds)
        freed: set[int] = set()
        for group in groups:
            if group in freed:
                continue
            for index, (hold, covered) in enumerate(_coverage(change_dir, holds)):
                if hold.status == RELEASED or group not in covered:
                    continue
                if hold.status == DONE:
                    raise HoldRefused(
                        f"group {group} of change {change_dir.name} is done, not held"
                    )
                out[index] = hold.model_copy(update={"status": RELEASED})
                freed |= covered
                break
            else:
                raise HoldRefused(f"group {group} of change {change_dir.name} is not held")
        _write(path, out)
        return tuple(sorted(freed))


def release_hold(change_dir: Path, group: int) -> None:
    """Give back the work of the hold that has `group`; raises `HoldRefused` when none holds it
    or the hold is done."""
    release_holds(change_dir, (group,))


def record_done(change_dir: Path, groups: Sequence[int], *, merged_by: str, at: datetime) -> None:
    """Mark `groups` done in the hold that has them, splitting off the groups still held;
    raises `HoldRefused` for a group no hold has."""
    path = external_path(change_dir)
    with file_lock(_lock(path)):
        out: list[Hold] = []
        todo = set(groups)
        for hold, covered in _coverage(change_dir, read_holds(change_dir)):
            mine = covered & todo
            if hold.status != HELD or not mine:
                out.append(hold)
                continue
            todo -= mine
            done = {"scope": tuple(sorted(mine)), "status": DONE, "merged_by": merged_by}
            out.append(hold.model_copy(update={**done, "done_at": at}))
            # What is left of an `all` hold stays `all`, so groups added later are held too.
            if rest := covered - mine:
                scope = "all" if hold.scope == "all" else tuple(sorted(rest))
                out.append(hold.model_copy(update={"scope": scope}))
        if todo:
            raise HoldRefused(f"group {min(todo)} of change {change_dir.name} is not held")
        _write(path, out)


class HoldRow(Frozen):
    """One hold as `abk external list` and `abk status` show it."""

    change: str
    groups: tuple[int, ...] | Literal["all"]
    holder: str
    link: str
    status: str
    items: dict[str, str | list[str]]
    note: str
    since: datetime
    age: str
    units: tuple[str, ...]
    waiting: tuple[str, ...]


def age_text(since: datetime, now: datetime) -> str:
    seconds = max(0, int((now - since).total_seconds()))
    for size, suffix in ((86400, "d"), (3600, "h")):
        if seconds >= size:
            return f"{seconds // size}{suffix}"
    return f"{seconds // 60}m"


def hold_rows(changes_dir: Path, units: Sequence[StoredUnit], now: datetime) -> list[HoldRow]:
    """Every hold of every change, with the held units it keeps from starting and the units
    that wait on them."""
    held = held_units(changes_dir, units)
    rows: list[HoldRow] = []
    folders = sorted(changes_dir.iterdir()) if changes_dir.is_dir() else []
    for folder in (path for path in folders if path.is_dir()):
        for hold in read_holds(folder):
            mine = (
                {uid for uid, found in held.items() if found == hold}
                if hold.status == HELD
                else set()
            )
            waiting = tuple(
                unit.id for unit in units if mine & set(unit.depends_on) and unit.id not in mine
            )
            rows.append(
                HoldRow(
                    change=folder.name,
                    groups=hold.scope,
                    holder=hold.holder,
                    link=hold.link,
                    status=hold.status,
                    items=hold.items,
                    note=hold.note,
                    since=hold.since,
                    age=age_text(hold.since, now),
                    units=tuple(sorted(mine)),
                    waiting=waiting,
                )
            )
    return rows


def hold_text(row: HoldRow) -> str:
    """A hold on one line."""
    groups = row.groups if row.groups == "all" else ",".join(str(n) for n in row.groups)
    text = f"{row.change} groups {groups}: {row.status} by {row.holder} ({row.link}), {row.age}"
    if row.units:
        text += f"; units {', '.join(row.units)}"
    if row.waiting:
        text += f"; waiting: {', '.join(row.waiting)}"
    return text


def hold_status_lines(changes_dir: Path, units: Sequence[StoredUnit], now: datetime) -> list[str]:
    """The `abk status` section for holds still held; none when nothing is."""
    rows = [row for row in hold_rows(changes_dir, units, now) if row.status == HELD]
    return ["external holds:", *(f"  {hold_text(row)}" for row in rows)] if rows else []
