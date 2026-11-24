"""Hands a hold's blocking to the board once the board blocks (spec: external-hold-adoption).

A hold is handed over when every group it covers is adopted and has someone other than the sync
account assigned on its group item or a task under it: the claim gate and the inbound sync then
block each of those groups. Otherwise the hold keeps blocking and says which groups have nobody
assigned. A handed-over hold is never revived here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.pipeline.external_file import HELD, hold_groups, read_holds, record_board
from agent_build_kit.pipeline.tracker_file import TrackerFile
from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.levels import task_group_key
from agent_build_kit.trackers.start_decision import others


def _assigned(tracker: Tracker, file: TrackerFile, key: str, sync: str) -> list[str]:
    """Who other than the sync account is assigned on the group item `key` or a task under it."""
    entry = file.groups.get(key)
    if entry is None or not entry.adopted:
        return []
    ids = [entry.id, *(task.id for name, task in file.tasks.items() if task_group_key(name) == key)]
    people: list[str] = []
    for item_id in ids:
        people.extend(who for who in others(tracker.get(item_id), sync) if who not in people)
    return people


def hand_over(tracker: Tracker, files: Mapping[str, TrackerFile], changes_dir: Path) -> None:
    """Compare each hold still held with the board and record what it shows."""
    sync = ""
    for name, file in files.items():
        folder = changes_dir / name
        for hold in read_holds(folder):
            if hold.status != HELD:
                continue
            groups = sorted(hold_groups(folder, hold))
            keys = {number: f"{name}:{number}" for number in groups}
            if not any(key in file.groups and file.groups[key].adopted for key in keys.values()):
                continue
            sync = sync or tracker.identity().name
            by_group = {number: _assigned(tracker, file, key, sync) for number, key in keys.items()}
            people = list(dict.fromkeys(who for found in by_group.values() for who in found))
            waiting = [number for number, found in by_group.items() if not found]
            record_board(folder, hold, people, waiting)
