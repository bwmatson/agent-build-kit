"""A recording tracker and a place to run the reconciler against it."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from agent_build_kit import trackers
from agent_build_kit.pipeline.tracker_file import TrackerFile, mapping_target, write_tracker
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.trackers.base import Item, ItemKind
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.local import LocalTracker
from agent_build_kit.trackers.reconciler import PassReport, reconcile
from tests.trackers.board_support import CHANGE, REPO_URL, write_change

READS = frozenset(
    {"capabilities", "identity", "get", "children", "changed_since", "find_by_marker"}
)
SYNC = "sync-bot"


class Call(NamedTuple):
    name: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class RecordingTracker(LocalTracker):
    """The stand-in tracker that records every call. `fail` is asked before each call and may
    return an error to raise instead; `lose_answer` names a marker whose create lands on the
    board and then raises, once."""

    def __init__(self, levels: Sequence[ItemKind] | None = None) -> None:
        super().__init__(levels=levels, who=SYNC)
        self.calls: list[Call] = []
        self.fail: Callable[[Call], Exception | None] = lambda call: None
        self.lose_answer: str | None = None

    def _enter(self, name: str, *args: Any, **kwargs: Any) -> None:
        call = Call(name, args, kwargs)
        self.calls.append(call)
        if (error := self.fail(call)) is not None:
            raise error

    def writes(self) -> list[Call]:
        return [call for call in self.calls if call.name not in READS]

    def made(self, name: str) -> list[Call]:
        return [call for call in self.calls if call.name == name]

    def identity(self):  # noqa: ANN201
        self._enter("identity")
        return super().identity()

    def get(self, item_id: str) -> Item:
        self._enter("get", item_id)
        return super().get(item_id)

    def children(self, item_id: str) -> Sequence[Item]:
        self._enter("children", item_id)
        return super().children(item_id)

    def find_by_marker(self, marker: str) -> Item | None:
        self._enter("find_by_marker", marker)
        return super().find_by_marker(marker)

    def create(
        self,
        kind: ItemKind,
        title: str,
        body: str = "",
        parent: str | None = None,
        *,
        markers: Sequence[str] = (),
        fields: Mapping[str, str] | None = None,
    ) -> Item:
        self._enter("create", kind, title, body, parent, markers=tuple(markers), fields=fields)
        item = super().create(kind, title, body, parent, markers=markers, fields=fields)
        if self.lose_answer is not None and self.lose_answer in markers:
            self.lose_answer = None
            raise RuntimeError("the answer to the create never arrived")
        return item

    def update(
        self, item_id: str, changes: Mapping[str, str], expected_revision: str | None = None
    ) -> Item:
        self._enter("update", item_id, dict(changes), expected_revision)
        return super().update(item_id, changes, expected_revision)

    def set_assignee(self, item_id: str, who: str, expected_revision: str | None = None) -> Item:
        self._enter("set_assignee", item_id, who, expected_revision)
        return super().set_assignee(item_id, who, expected_revision)

    def claim(self, item_id: str) -> bool:
        self._enter("claim", item_id)
        return super().claim(item_id)

    def link(self, item_id: str, relation: str, target_id: str):  # noqa: ANN201
        self._enter("link", item_id, relation, target_id)
        return super().link(item_id, relation, target_id)

    def comment(self, item_id: str, text: str) -> None:
        self._enter("comment", item_id, text)
        super().comment(item_id, text)


class World:
    """One repo, its changes folder, its state folder and a recording tracker registered as the
    tracker of the section's kind."""

    def __init__(self, tmp_path: Path, section: TrackerSection, tracker: RecordingTracker) -> None:
        self.section = section
        self.tracker = tracker
        self.changes_dir = tmp_path / "changes"
        self.changes_dir.mkdir()
        self.state_dir = tmp_path / "state"
        self.state_dir.mkdir()
        self.logs: list[str] = []
        write_change(self.changes_dir)
        trackers.register(section.kind, lambda _section: tracker)

    @property
    def change_dir(self) -> Path:
        return self.changes_dir / CHANGE

    @property
    def snapshot(self) -> Path:
        return self.state_dir / "tracker-app.json"

    def item_id(self, marker: str) -> str:
        found = self.tracker.find_by_marker(marker)
        assert found is not None, f"{marker} is not on the board"
        return found.id

    def record_epic(self, epic_id: str) -> None:
        write_tracker(
            self.change_dir,
            TrackerFile(kind=self.section.kind, target=mapping_target(self.section), epic=epic_id),
        )

    def run(self, units: Sequence[Unit] = (), *, changes: Sequence[str] = (CHANGE,)) -> PassReport:
        return reconcile(
            "app",
            changes_dir=self.changes_dir,
            changes=changes,
            units=units,
            repo_url=REPO_URL,
            state_dir=self.state_dir,
            log=self.logs.append,
        )
