"""A planning root whose repo `app` mirrors to a recording stand-in board, and `abk tracker` run
over it, for the tests of the `abk tracker` commands.

The commands' JSON forms are the contract these tests fix: `status --json` prints
`{"repos": {<repo>: {...}}}` with the keys `target`, `identity`, `changes`, `groups`, `tasks`,
`to_create`, `last_push`, `last_pull`, `conflicts` (a list) and `error`; `conflicts --json` prints
`{"conflicts": [{"id", "repo", "change", "item_id", "field", "spec_value", "tracker_value"}]}`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.tracker_file import (
    ConflictRecord,
    TrackerFile,
    read_tracker,
    write_tracker,
)
from agent_build_kit.trackers.config import TrackerSection
from tests.cli.e2e_hold_fakes import abk, planning
from tests.factories import init_repo
from tests.trackers.board_support import CHANGE, groups_tasks, write_change
from tests.trackers.reconciler_support import RecordingTracker

KIND = "azure_devops"
APP = "app"
ORGANIZATION = "example-org"
NONE_CONFIGURED = "no tracker configured"


LEVELS = ("change", "group")
# The board's words for each level, none of them a level's own name.
BOARD_TYPES = {"epic": "Epic", "change": "Issue", "group": "Task", "task": "Subtask"}


def section_text(
    *,
    create_cap: int | None = None,
    levels: tuple[str, ...] = LEVELS,
    types: dict[str, str] = BOARD_TYPES,
) -> str:
    """A section under a repo with these levels, whose board types differ from the level names."""
    cap = f"      create_cap: {create_cap}\n" if create_cap else ""
    words = ", ".join(f"{level}: {word}" for level, word in types.items())
    return (
        "    tracker:\n"
        f"      kind: {KIND}\n"
        "      token_env: TRACKER_PAT\n"
        f"      levels: [{', '.join(levels)}]\n"
        "      epic: true\n"
        f"{cap}"
        "      azure_devops:\n"
        f"        organization: {ORGANIZATION}\n"
        "        project: Example Project\n"
        "        team: Example Team\n"
        "        area_path: Example Project\\Area\n"
        "        iteration_path: Example Project\\Iteration 1\n"
        f"        types: {{{words}}}\n"
        "        states: {new: To Do, active: Doing, done: Done}\n"
    )


class Mirror:
    """The planning root, a recording board registered for the section's kind, and the commands.
    `section` is the text of the repo's `tracker` block (empty for none)."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        groups: int = 2,
        create_cap: int | None = None,
        section: str | None = None,
        levels: tuple[str, ...] = LEVELS,
        types: dict[str, str] = BOARD_TYPES,
        platform: bool = False,
    ) -> None:
        """`platform` adds a second repo with the same section, whose groups a change can have
        beside `app`'s."""
        text = section_text(create_cap=create_cap, levels=levels, types=types)
        text = text if section is None else section
        self.config = planning(tmp_path, app_tests=text, platform_tests=text if platform else None)
        init_repo(self.config.parent)
        self.root = self.config.parent
        self.changes_dir = self.root / "openspec" / "changes"
        self.changes_dir.mkdir(parents=True)
        write_change(self.changes_dir, tasks=groups_tasks(groups))
        self.board = RecordingTracker(board_types=types)
        # How many of the next builds of the tracker fail, for a test of one repo's failure.
        self.factory_failures = 0

    @property
    def change_dir(self) -> Path:
        return self.changes_dir / CHANGE

    @contextmanager
    def served(self) -> Iterator[None]:
        def factory(section: TrackerSection) -> RecordingTracker:
            if self.factory_failures:
                self.factory_failures -= 1
                raise RuntimeError("the tracker could not be built")
            return self.board

        trackers.register(KIND, factory)
        try:
            yield
        finally:
            trackers.unregister(KIND)

    def run(self, capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
        """`abk tracker <argv>`: the exit code and everything it printed, out and error."""
        with self.served():
            code, out, err = abk(self.config, capsys, "tracker", *argv)
        return code, "\n".join([*out, *err])

    def run_json(self, capsys: pytest.CaptureFixture[str], *argv: str) -> Any:
        """The one JSON document `abk tracker <argv> --json` printed."""
        with self.served():
            code, out, err = abk(self.config, capsys, "tracker", *argv, "--json")
        assert code == 0, err
        return json.loads("\n".join(out))

    def set_epic_line(self, reference: str) -> None:
        """Put an `Epic:` line above the first group of the change's `tasks.md`."""
        path = self.change_dir / "tasks.md"
        title, _, rest = path.read_text().partition("\n")
        path.write_text(f"{title}\n\nEpic: {reference}\n{rest}")

    def tracker_file(self) -> TrackerFile:
        recorded = read_tracker(self.change_dir)
        assert recorded is not None, "the change has no tracker.yaml"
        return recorded

    def record_conflict(self, item_id: str, field: str, spec_value: str, board_value: str) -> None:
        """Add an open conflict to the change's tracker file, as the pull pass records one."""
        record = ConflictRecord(
            item_id=item_id,
            field=field,
            spec_value=spec_value,
            tracker_value=board_value,
            who="alice@example.test",
            when="2026-01-01T00:00:00Z",
        )
        write_tracker(
            self.change_dir, self.tracker_file().model_copy(update={"conflicts": (record,)})
        )

    def files(self) -> dict[str, int]:
        """Every file under the planning root with its size, for a before and after."""
        return {
            str(path.relative_to(self.root)): path.stat().st_size
            for path in sorted(self.root.rglob("*"))
            if path.is_file() and ".git" not in path.parts
        }


def create_kinds(board: RecordingTracker) -> list[str]:
    """The kind of each item the board was asked to create, in order."""
    return [call.args[0] for call in board.made("create")]
