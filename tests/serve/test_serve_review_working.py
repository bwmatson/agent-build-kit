"""A unit's uncommitted changes from a chat are shown apart from its commits, and a thread,
which anchors to a commit, is refused on them (spec: ui-review)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.serve.review import ReviewStore
from tests.attach_driver import checked_out, head
from tests.serving import seed_pipeline

UNIT = "feature/2"
WORKING = f"/api/units/{UNIT}/review/working"


@pytest.fixture
def tree(inst: Installation) -> Path:
    seed_pipeline(inst)
    return checked_out(inst, UNIT)


def store(inst: Installation) -> ReviewStore:
    directory = inst.state_dir / "reviews"
    directory.mkdir(parents=True, exist_ok=True)
    return ReviewStore(directory)


def test_the_changes_a_chat_left_in_the_worktree_are_returned_as_their_own_patch(
    tree: Path, api: httpx.Client
) -> None:
    (tree / "base.txt").write_text("base\nedited\n")
    (tree / "notes.txt").write_text("a new file\n")

    answer = api.get(WORKING)

    assert answer.status_code == 200
    body = answer.json()
    assert body["files"] == ["base.txt", "notes.txt"]
    assert "+edited" in body["patch"]
    assert "+a new file" in body["patch"], "a file git does not track yet is shown too"
    assert body["commit"] == head(tree), "against the commit the worktree stands on"


def test_the_branch_diff_does_not_hold_the_uncommitted_changes(
    tree: Path, api: httpx.Client
) -> None:
    (tree / "notes.txt").write_text("a new file\n")

    committed = api.get(f"/api/units/{UNIT}/diff").json()

    assert "notes.txt" not in committed["patch"]


def test_a_unit_whose_worktree_is_clean_has_no_working_changes(
    tree: Path, api: httpx.Client
) -> None:
    answer = api.get(WORKING)

    assert answer.status_code == 200
    assert answer.json()["files"] == []
    assert answer.json()["patch"] == ""


def test_a_unit_with_no_worktree_has_no_working_changes(
    inst: Installation, api: httpx.Client
) -> None:
    seed_pipeline(inst)

    answer = api.get(WORKING)

    assert answer.status_code == 200
    assert answer.json()["files"] == []


def test_a_thread_on_uncommitted_lines_is_refused_with_the_reason_and_stores_nothing(
    inst: Installation, tree: Path, api: httpx.Client
) -> None:
    (tree / "notes.txt").write_text("a new file\n")

    answer = api.post(
        f"/api/units/{UNIT}/review/threads",
        json={"path": "notes.txt", "side": "new", "line": 1, "body": "why?", "uncommitted": True},
    )

    assert answer.status_code == 409
    assert "uncommitted" in answer.json()["detail"]
    assert store(inst).read(UNIT).threads == ()
