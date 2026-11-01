"""The manual parent of a change: resolved by reads, checked by board type, and only ever read.

Every scenario runs against the local stand-in and against the Azure DevOps tracker over its
HTTP stand-in, which is the board the manual epic exists for.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Protocol

import pytest

from agent_build_kit.forges.transport import clear_credentials
from agent_build_kit.pipeline.tracker_file import (
    TrackerFile,
    mapping_target,
    parent_item,
    read_tracker,
    with_manual_parent,
    write_tracker,
)
from agent_build_kit.pipeline.work_graph import epic_reference
from agent_build_kit.settings import settings
from agent_build_kit.trackers.base import Item, ItemKind
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.local import EPIC_TYPE, LocalTracker
from agent_build_kit.trackers.manual_parent import (
    ManualParent,
    ManualParentError,
    ManualParentSource,
    resolve_manual_parent,
)
from tests.forges.conftest import PAT
from tests.task_priority_files import tasks_md
from tests.trackers import contract
from tests.trackers.ado_support import section, tracker_on
from tests.trackers.ado_work_item_host import WorkItemHost


@pytest.fixture(autouse=True)
def pat(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A PAT is configured, as `rest_env` does, but a process may start: the mapping file's
    lock asks git where the planning repository keeps its local files."""
    monkeypatch.setattr(settings, "ado_pat", PAT)
    clear_credentials()
    yield
    clear_credentials()


TITLE = "Roadmap: Phase One"


class Creates(Protocol):
    def create(
        self, kind: ItemKind, title: str, body: str = "", parent: str | None = None
    ) -> Item: ...


class Board:
    """A board with a manual epic on it, read through `source` and written through `tracker`."""

    def __init__(
        self,
        source: ManualParentSource,
        tracker: Creates,
        config: TrackerSection,
        epic_id: str,
        first_level: Callable[[str], str],
        epic_writes: Callable[[], list[str]],
    ) -> None:
        self.source = source
        self.tracker = tracker
        # The board's configuration: the levels, with the epic level on.
        self.config = config
        self.expected = config.level_types["epic"]
        self.epic_id = epic_id
        # Makes an item of the first level, which a person did not make as the epic; its id.
        self.first_level = first_level
        # What was sent to the epic that is not a read.
        self.epic_writes = epic_writes

    def resolve(self, reference: str, *, in_scope: bool = True) -> ManualParent:
        return resolve_manual_parent(
            self.source, reference, expected=self.expected, in_scope=lambda _: in_scope
        )


def local_board() -> Board:
    tracker = LocalTracker(levels=["change"])
    epic = tracker.add_epic(TITLE)
    shape = contract.shape_of(tracker, tracker.as_identity("someone-else"), ("change",), epic)
    return Board(
        tracker,
        shape.tracker,
        TrackerSection(
            kind="local",
            levels=("change",),
            epic=True,
            types={"epic": EPIC_TYPE, "change": "change"},
        ),
        epic.id,
        lambda title: tracker.create("change", title).id,
        lambda: shape.epic_writes,
    )


def azure_board() -> Board:
    host = WorkItemHost()
    tracker = tracker_on(host, "basic")
    epic_id = host.seed("Epic", TITLE)

    def writes() -> list[str]:
        return [s.method for s in host.calls(route=f"wit/workitems/{epic_id}") if s.method != "GET"]

    return Board(
        tracker,
        tracker,
        section("basic"),
        epic_id,
        lambda title: host.seed("Issue", title),
        writes,
    )


@pytest.fixture(params=[local_board, azure_board], ids=["local", "azure"])
def board(request: pytest.FixtureRequest) -> Board:
    return request.param()


def test_an_id_resolves_to_the_existing_item(board: Board) -> None:
    assert board.resolve(board.epic_id).id == board.epic_id


def test_an_exact_title_resolves_to_the_existing_item(board: Board) -> None:
    assert board.resolve(TITLE).id == board.epic_id


@pytest.mark.parametrize("loose", ["Roadmap", TITLE.lower(), TITLE.upper()])
def test_a_part_of_a_title_or_another_case_does_not_resolve(board: Board, loose: str) -> None:
    with pytest.raises(ManualParentError):
        board.resolve(loose)


def test_a_missing_id_is_refused_naming_it(board: Board) -> None:
    with pytest.raises(ManualParentError) as refused:
        board.resolve("99999")

    assert "99999" in str(refused.value)


def test_a_first_level_item_is_refused_naming_the_id_and_both_types(board: Board) -> None:
    other = board.first_level("Not an epic")

    with pytest.raises(ManualParentError) as refused:
        board.resolve(other)

    message = str(refused.value)
    assert other in message and board.expected in message


def test_an_item_out_of_scope_is_refused(board: Board) -> None:
    with pytest.raises(ManualParentError) as refused:
        board.resolve(board.epic_id, in_scope=False)

    assert board.epic_id in str(refused.value)


class Counting:
    """A manual parent source that counts the reads sent to the one it wraps."""

    def __init__(self, inner: ManualParentSource) -> None:
        self.inner = inner
        self.reads = 0

    def read_manual_parent(self, item_id: str) -> ManualParent | None:
        self.reads += 1
        return self.inner.read_manual_parent(item_id)

    def find_manual_parents(self, title: str) -> Sequence[ManualParent]:
        self.reads += 1
        return self.inner.find_manual_parents(title)


def mapped(
    board: Board, tmp_path: Path, head: str, *, epic: bool = True, recorded: str | None = None
) -> tuple[TrackerFile, TrackerSection, Counting, Path]:
    """The mapping file of a change whose tasks.md header is `head`, after the manual parent is
    resolved, written and read back; the section (with the epic level on or off) and the reads
    made."""
    folder = tmp_path / "change"
    folder.mkdir()
    (folder / "tasks.md").write_text(tasks_md(None, head=head))
    config = board.config.model_copy(update={"epic": epic})
    source = Counting(board.source)
    start = TrackerFile(kind=config.kind, target=mapping_target(config), epic=recorded)
    resolved = with_manual_parent(
        start, config, epic_reference(folder / "tasks.md"), source, lambda _: True
    )
    write_tracker(folder, resolved)
    found = read_tracker(folder)
    assert found is not None
    return found, config, source, folder


def place(board: Board, found: TrackerFile, config: TrackerSection) -> Item:
    """The change item, created under the parent the file gives it."""
    return board.tracker.create(
        "change", "Change", "body", parent_item(found, config, "change", "feature")
    )


@pytest.mark.parametrize("by", ["id", "title"])
def test_a_tagged_change_records_its_manual_parent_and_the_change_item_hangs_under_it(
    board: Board, tmp_path: Path, by: str
) -> None:
    reference = board.epic_id if by == "id" else TITLE

    found, config, _, _ = mapped(board, tmp_path, f"Epic: {reference}\n")

    assert found.epic == board.epic_id
    assert parent_item(found, config, "change", "feature") == board.epic_id
    assert place(board, found, config).parent_id == board.epic_id
    assert board.epic_writes() == []


def test_a_change_with_no_line_has_no_epic_level_and_its_change_item_no_parent(
    board: Board, tmp_path: Path
) -> None:
    found, config, source, _ = mapped(board, tmp_path, "")

    assert found.epic is None
    assert parent_item(found, config, "change", "feature") is None
    assert place(board, found, config).parent_id is None
    assert source.reads == 0


def test_a_repo_with_no_epic_resolves_nothing_even_when_the_change_has_the_line(
    board: Board, tmp_path: Path
) -> None:
    found, config, source, _ = mapped(board, tmp_path, f"Epic: {board.epic_id}\n", epic=False)

    assert found.epic is None
    assert parent_item(found, config, "change", "feature") is None
    assert place(board, found, config).parent_id is None
    assert source.reads == 0


def test_a_recorded_epic_is_kept_and_nothing_is_read(board: Board, tmp_path: Path) -> None:
    found, _, source, _ = mapped(board, tmp_path, f"Epic: {board.epic_id}\n", recorded="77")

    assert found.epic == "77"
    assert source.reads == 0


def test_an_unusable_line_is_refused_and_records_nothing(board: Board, tmp_path: Path) -> None:
    with pytest.raises(ManualParentError):
        mapped(board, tmp_path, "Epic: 99999\n")


def test_over_the_whole_run_the_only_calls_on_the_manual_item_are_reads(board: Board) -> None:
    parent = board.resolve(TITLE)
    board.tracker.create("change", "Change", "body", parent.id)
    board.resolve(board.epic_id)

    assert board.epic_writes() == []


def test_a_title_made_of_digits_is_found_by_title_when_no_item_has_that_id() -> None:
    tracker = LocalTracker()
    epic = tracker.add_epic("2026")

    found = resolve_manual_parent(tracker, "2026", expected=EPIC_TYPE, in_scope=lambda _: True)

    assert found.id == epic.id


@pytest.mark.parametrize("type_", ["Bug", "Feature"])
def test_an_azure_item_of_another_type_is_refused_naming_the_id_and_both_types(type_: str) -> None:
    host = WorkItemHost()
    tracker = tracker_on(host, "basic")
    other = host.seed(type_, "Not an epic")

    with pytest.raises(ManualParentError) as refused:
        resolve_manual_parent(tracker, other, expected="Epic", in_scope=lambda _: True)

    message = str(refused.value)
    assert other in message and type_ in message and "Epic" in message
    assert [s.method for s in host.seen if s.route == f"wit/workitems/{other}"] == ["GET"]


class Candidates:
    """A source whose title search answers what a board's loose search does."""

    def __init__(self, found: Sequence[ManualParent]) -> None:
        self.found = found

    def read_manual_parent(self, item_id: str) -> ManualParent | None:
        return None

    def find_manual_parents(self, title: str) -> Sequence[ManualParent]:
        return self.found


def parent(item_id: str, title: str) -> ManualParent:
    return ManualParent(id=item_id, title=title, type="Epic")


def resolve_among(found: Sequence[ManualParent], reference: str) -> ManualParent:
    return resolve_manual_parent(
        Candidates(found), reference, expected="Epic", in_scope=lambda _: True
    )


def test_the_exact_title_is_picked_from_loose_candidates() -> None:
    candidates = [
        parent("1", "Roadmap: Phase One and Two"),
        parent("2", "roadmap: phase one"),
        parent("3", TITLE),
    ]

    assert resolve_among(candidates, TITLE).id == "3"


def test_candidates_that_are_not_exact_resolve_to_nothing() -> None:
    candidates = [parent("1", "Roadmap: Phase One and Two"), parent("2", "roadmap: phase one")]

    with pytest.raises(ManualParentError):
        resolve_among(candidates, TITLE)


def test_two_items_with_the_exact_title_are_refused_naming_both_ids() -> None:
    with pytest.raises(ManualParentError) as refused:
        resolve_among([parent("7", TITLE), parent("8", TITLE)], TITLE)

    assert "7" in str(refused.value) and "8" in str(refused.value)
