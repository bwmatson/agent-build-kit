"""The pull request description links the board items of the groups a unit built, and the pull
request is attached to each of them once (spec: tracker-push)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.pr_body import build_pr_body
from agent_build_kit.pipeline.tracker_file import (
    Synced,
    TaskEntry,
    TrackerFile,
    mapping_target,
    write_tracker,
)
from agent_build_kit.trackers.config import section_for
from agent_build_kit.trackers.pr_attach import attach_pull_request
from tests.factories import stored_unit
from tests.trackers.board_support import CHANGE, TYPES, write_change
from tests.trackers.reconciler_support import RecordingTracker
from tests.trackers.tracker_section_support import AZURE_BLOCK, GITHUB_BLOCK, configure

PR_URL = "https://example.test/example/app/pull/7"
EPIC_ID = "259"
CHANGE_ID, GROUP_1_ID, GROUP_2_ID = "100", "101", "102"
BUILT = (1, 2)


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")
    trackers.unregister("github")


def azure(levels: list[str], pr_links: Any = "lowest") -> dict[str, Any]:
    return {
        "kind": "azure_devops",
        "levels": levels,
        "epic": True,
        "pr_links": pr_links,
        "azure_devops": {**AZURE_BLOCK, "types": TYPES},
    }


def github(levels: list[str]) -> dict[str, Any]:
    return {
        "kind": "github",
        "token_env": "TRACKER_TOKEN",
        "levels": levels,
        "github": GITHUB_BLOCK,
    }


def board(tmp_path: Path, raw: dict[str, Any] | None) -> Path:
    """A change whose board is mirrored under `raw`'s section; the changes folder."""
    configure(app=raw)
    changes = tmp_path / "changes"
    changes.mkdir()
    write_change(changes)
    if raw is not None:
        section = section_for("app")
        assert section is not None
        write_tracker(
            changes / CHANGE,
            TrackerFile(
                kind=section.kind,
                target=mapping_target(section),
                change=Synced(id=CHANGE_ID),
                epic=EPIC_ID,
                groups={
                    f"{CHANGE}:1": Synced(id=GROUP_1_ID),
                    f"{CHANGE}:2": Synced(id=GROUP_2_ID),
                },
            ),
        )
    return changes


def body(changes: Path) -> str:
    unit = stored_unit(f"{CHANGE}/1", change=CHANGE, groups=BUILT, repo="app")
    return build_pr_body(unit, graph=[unit], base="main", changes_dir=changes)


def attach(changes: Path, state: Path) -> tuple[str, ...]:
    unit = stored_unit(f"{CHANGE}/1", change=CHANGE, groups=BUILT, repo="app")
    return attach_pull_request(unit, changes_dir=changes, state_dir=state, pr_url=PR_URL)


def watched() -> RecordingTracker:
    tracker = RecordingTracker()
    trackers.register("azure_devops", lambda _section: tracker)
    return tracker


def test_each_built_groups_item_gets_an_ab_line(tmp_path: Path) -> None:
    changes = board(tmp_path, azure(["change", "group"]))

    text = body(changes)

    assert f"AB#{GROUP_1_ID}" in text
    assert f"AB#{GROUP_2_ID}" in text
    assert f"AB#{CHANGE_ID}" not in text


def test_each_built_groups_item_gets_the_pull_request_attached_once(tmp_path: Path) -> None:
    changes = board(tmp_path, azure(["change", "group"]))
    tracker = watched()
    state = tmp_path / "state"
    state.mkdir()

    first = attach(changes, state)
    second = attach(changes, state)

    assert sorted(first) == [f"{CHANGE}:1", f"{CHANGE}:2"]
    assert sorted(call.args[0] for call in tracker.made("link")) == [GROUP_1_ID, GROUP_2_ID]
    assert all(call.args[2] == PR_URL for call in tracker.made("link"))
    assert second == ()
    assert len(tracker.made("link")) == 2


def test_all_links_every_level_and_the_epic_is_never_one(tmp_path: Path) -> None:
    changes = board(tmp_path, azure(["change", "group"], "all"))
    tracker = watched()
    state = tmp_path / "state"
    state.mkdir()

    text = body(changes)
    attach(changes, state)

    for item_id in (CHANGE_ID, GROUP_1_ID, GROUP_2_ID):
        assert f"AB#{item_id}" in text
    assert f"AB#{EPIC_ID}" not in text
    assert sorted(call.args[0] for call in tracker.made("link")) == [
        CHANGE_ID,
        GROUP_1_ID,
        GROUP_2_ID,
    ]


def test_a_list_of_levels_changes_the_targets(tmp_path: Path) -> None:
    changes = board(tmp_path, azure(["change", "group"], ["change"]))
    tracker = watched()
    state = tmp_path / "state"
    state.mkdir()

    text = body(changes)
    attach(changes, state)

    assert f"AB#{CHANGE_ID}" in text
    assert f"AB#{GROUP_1_ID}" not in text
    assert [call.args[0] for call in tracker.made("link")] == [CHANGE_ID]


def test_a_github_tracker_gets_a_part_of_line(tmp_path: Path) -> None:
    changes = board(tmp_path, github(["change", "group"]))

    text = body(changes)

    assert f"Part of #{GROUP_1_ID}" in text
    assert f"Part of #{GROUP_2_ID}" in text
    assert "AB#" not in text


def test_a_repo_with_no_tracker_gets_the_description_it_gets_today(tmp_path: Path) -> None:
    changes = board(tmp_path, None)
    tracker = watched()
    state = tmp_path / "state"
    state.mkdir()
    before = body(changes)
    # A leftover tracker file of a board the repo no longer names changes nothing.
    write_tracker(
        changes / CHANGE,
        TrackerFile(kind="azure_devops", target="x", change=Synced(id=CHANGE_ID)),
    )

    after = body(changes)

    assert after == before
    assert "AB#" not in after
    assert "Part of #" not in after
    assert attach(changes, state) == ()
    assert not tracker.calls


def test_a_conflicted_tracker_file_gives_a_description_with_no_tracker_line(
    tmp_path: Path,
) -> None:
    changes = board(tmp_path, azure(["change", "group"]))
    tracker = watched()
    state = tmp_path / "state"
    state.mkdir()
    (changes / CHANGE / "tracker.yaml").write_text("<<<<<<< ours\nkind: [\n=======\n>>>>>>> t\n")

    text = body(changes)

    assert "AB#" not in text
    assert attach(changes, state) == ()
    assert not tracker.calls


def test_a_tracker_file_of_another_board_gives_no_line_and_no_attachment(
    tmp_path: Path,
) -> None:
    changes = board(tmp_path, azure(["change", "group"]))
    tracker = watched()
    state = tmp_path / "state"
    state.mkdir()
    write_tracker(
        changes / CHANGE,
        TrackerFile(
            kind="azure_devops",
            target="azure_devops other/board@00000000",
            change=Synced(id=CHANGE_ID),
            groups={f"{CHANGE}:1": Synced(id=GROUP_1_ID)},
        ),
    )

    text = body(changes)

    assert "AB#" not in text
    assert attach(changes, state) == ()
    assert not tracker.calls


def test_with_a_task_level_each_task_of_the_built_groups_gets_a_line_and_the_pull_request(
    tmp_path: Path,
) -> None:
    changes = board(tmp_path, azure(["change", "group", "task"]))
    tracker = watched()
    state = tmp_path / "state"
    state.mkdir()
    section = section_for("app")
    assert section is not None
    ids = {
        f"{CHANGE}:{group}.{task}": str(200 + group * 10 + task)
        for group in BUILT
        for task in (1, 2)
    }
    write_tracker(
        changes / CHANGE,
        TrackerFile(
            kind=section.kind,
            target=mapping_target(section),
            change=Synced(id=CHANGE_ID),
            groups={f"{CHANGE}:1": Synced(id=GROUP_1_ID), f"{CHANGE}:2": Synced(id=GROUP_2_ID)},
            tasks={key: TaskEntry(id=item_id, text_hash="h") for key, item_id in ids.items()},
        ),
    )

    text = body(changes)
    attached = attach(changes, state)

    for item_id in ids.values():
        assert f"AB#{item_id}" in text
    assert f"AB#{GROUP_1_ID}" not in text
    assert sorted(attached) == sorted(ids)
    assert sorted(call.args[0] for call in tracker.made("link")) == sorted(ids.values())
