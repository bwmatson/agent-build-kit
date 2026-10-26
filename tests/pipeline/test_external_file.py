"""The hold file of a change: its fields, its checks, and that it stays out of the plan
(spec: external-work)."""

from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit import openspec
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.hooks.policy import decide
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.external_file import (
    DONE,
    FILE_NAME,
    RELEASED,
    Hold,
    HoldRefused,
    add_hold,
    blocked_groups,
    external_path,
    read_holds,
    write_holds,
)
from agent_build_kit.split.select import moved_files, plan_split
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.split_sources import source_installation, write_change

SINCE = datetime(2026, 10, 26, 9, 30, tzinfo=UTC)
GROUP = "## {n}. [app] [unit-test] Group {n}\n\n- [ ] {n}.1 Test: it\n"


def tasks_with(groups: int) -> str:
    return "# Tasks\n\n" + "\n".join(GROUP.format(n=n) for n in range(1, groups + 1))


def change_with(tmp_path: Path, groups: int = 3) -> Path:
    folder = tmp_path / "openspec" / "changes" / "feature"
    folder.mkdir(parents=True)
    (folder / "proposal.md").write_text("# feature\n")
    (folder / "tasks.md").write_text(tasks_with(groups))
    return folder


def hold(scope: object = (2, 3), **fields: object) -> Hold:
    base: dict[str, object] = {
        "scope": scope,
        "holder": "Sam Example",
        "link": "https://boards.example/items/42",
        "since": SINCE,
    }
    return Hold.model_validate({**base, **fields})


def test_a_hold_round_trips_with_every_field(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    written = hold(
        items={"feature": "100", "story": "101", "tasks": ["102", "103"]}, note="taken at stand-up"
    )

    add_hold(folder, written)

    assert read_holds(folder) == (written,)
    assert external_path(folder) == folder / FILE_NAME


def test_a_status_the_reader_does_not_know_keeps_its_groups_blocked(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    external_path(folder).write_text(
        "holds:\n"
        "  - scope: [2]\n"
        "    holder: Sam Example\n"
        "    link: https://boards.example/items/42\n"
        f"    since: {SINCE.isoformat()}\n"
        "    status: handed_over\n"
    )

    assert read_holds(folder)[0].status == "handed_over"
    assert blocked_groups(folder) == {2}


def test_done_and_released_holds_block_nothing(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    write_holds(
        folder,
        [hold((1,), status=DONE, merged_by="17", done_at=SINCE), hold((2,), status=RELEASED)],
    )

    assert blocked_groups(folder) == frozenset()


def test_an_overlapping_hold_is_refused_naming_the_group(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    add_hold(folder, hold((2,)))

    with pytest.raises(HoldRefused, match="group 2"):
        add_hold(folder, hold((2, 3), holder="Alex Example"))

    assert read_holds(folder) == (hold((2,)),)


def test_a_group_the_change_lacks_is_refused_naming_group_and_change(tmp_path: Path) -> None:
    folder = change_with(tmp_path)

    with pytest.raises(HoldRefused, match=r"group 7.*feature"):
        add_hold(folder, hold((7,)))

    assert read_holds(folder) == ()


def test_an_all_scope_covers_groups_added_later(tmp_path: Path) -> None:
    folder = change_with(tmp_path, groups=2)
    add_hold(folder, hold("all"))

    (folder / "tasks.md").write_text(tasks_with(3))

    assert blocked_groups(folder) == {1, 2, 3}


def test_adding_releasing_and_adding_again_leaves_the_plan_digest_alone(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    tasks = folder / "tasks.md"
    inst = make_installation(tmp_path)
    digest = cli.plan_digest(tasks, inst=inst)
    text = tasks.read_text()

    add_hold(folder, hold((2,)))
    assert cli.plan_digest(tasks, inst=inst) == digest
    write_holds(folder, [hold((2,), status=RELEASED)])
    assert cli.plan_digest(tasks, inst=inst) == digest
    add_hold(folder, hold((2,)))

    assert cli.plan_digest(tasks, inst=inst) == digest
    assert tasks.read_text() == text


@pytest.mark.parametrize("with_tasks", [True, False])
def test_check_passes_on_a_change_holding_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, with_tasks: bool
) -> None:
    inst = make_installation(tmp_path)
    folder = inst.changes_dir / "feature"
    folder.mkdir(parents=True)
    if with_tasks:
        (folder / "tasks.md").write_text(tasks_with(2))
    add_hold(folder, hold("all"))
    monkeypatch.setattr(openspec, "check", lambda root: (True, "all valid\n"))

    assert cli.cmd_check(argparse.Namespace(), inst) == 0


def test_a_hold_on_a_folder_without_tasks_blocks_nothing_yet(tmp_path: Path) -> None:
    folder = tmp_path / "openspec" / "changes" / "feature"
    folder.mkdir(parents=True)

    add_hold(folder, hold("all"))

    assert read_holds(folder)[0].scope == "all"
    assert blocked_groups(folder) == frozenset()


def test_an_agent_step_cannot_write_the_file(tmp_path: Path) -> None:
    code, planning = tmp_path / "code", tmp_path / "planning"
    folder = planning / "openspec" / "changes" / "feature"
    for place in (code, folder):
        place.mkdir(parents=True)
    for place in (code, planning):
        subprocess.run(["git", "init", "-q"], cwd=place, check=True)

    def write(target: Path) -> dict | None:
        payload = {
            "tool_name": "Write",
            "cwd": str(code),
            "tool_input": {"file_path": str(target)},
        }
        return decide(payload, planning_repo=planning, planning_change_dir=folder)

    denied = write(external_path(folder))

    assert denied is not None
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_archiving_keeps_the_file(tmp_path: Path) -> None:
    folder = change_with(tmp_path)
    add_hold(folder, hold((2,)))
    archive = tmp_path / "openspec" / "changes" / "archive" / "2026-10-26-feature"

    def run(args: list[str], *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess:
        archive.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(archive)
        return subprocess.CompletedProcess(args, 0, "archived\n", "")

    done = archive_ready_changes(
        [stored_unit("feature/1", change="feature", state="merged")],
        planning_repo=tmp_path,
        run=run,
    )

    assert done == ["feature"]
    assert read_holds(archive) == (hold((2,)),)


def test_the_split_tools_list_includes_the_file(tmp_path: Path) -> None:
    source = source_installation(tmp_path / "source")
    folder = write_change(source, "feature", ["app"])
    add_hold(folder, hold((1,)))

    listed = moved_files(source, plan_split(source, "app"))

    assert folder / FILE_NAME in listed
