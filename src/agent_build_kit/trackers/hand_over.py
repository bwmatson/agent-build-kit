"""Hands a hold's blocking to the board once the board blocks (spec: external-hold-adoption).

A hold whose adopted group items, or a task under one, are assigned to someone other than the sync
account is blocked by the claim gate and the inbound sync already, so it is marked handed over. A
hold with nobody assigned keeps blocking and says so. A handed-over hold is never revived here.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agent_build_kit.pipeline.external_file import HELD, hold_groups, read_holds, record_board
from agent_build_kit.pipeline.tracker_file import TrackerFile
from agent_build_kit.trackers.base import Tracker
from agent_build_kit.trackers.levels import task_group_key
from agent_build_kit.trackers.start_decision import others


def hand_over(tracker: Tracker, files: Mapping[str, TrackerFile], changes_dir: Path) -> None:
    """Compare each hold still held with the board and record what it shows."""
    sync = ""
    for name, file in files.items():
        folder = changes_dir / name
        for hold in read_holds(folder):
            if hold.status != HELD:
                continue
            keys = [f"{name}:{number}" for number in sorted(hold_groups(folder, hold))]
            adopted = [key for key in keys if key in file.groups and file.groups[key].adopted]
            if not adopted:
                continue
            sync = sync or tracker.identity().name
            ids = [
                *(file.groups[key].id for key in adopted),
                *(entry.id for key, entry in file.tasks.items() if task_group_key(key) in adopted),
            ]
            people: list[str] = []
            for item_id in ids:
                people.extend(
                    who for who in others(tracker.get(item_id), sync) if who not in people
                )
            record_board(folder, hold, people)
