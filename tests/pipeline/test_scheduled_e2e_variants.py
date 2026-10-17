"""A due repo gets one scheduled change per declared split and `rest`; the due check and the open
check are per repo and split, read from the change names alone (spec: e2e-split-runs)."""

from __future__ import annotations

import argparse
import threading
from datetime import date, timedelta
from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_schedule import (
    PREFIX,
    scheduled_name,
    scheduled_parts,
    write_due,
)
from agent_build_kit.pipeline.work_graph import validate_tasks
from tests.e2e_schedule_fakes import (
    TODAY,
    ago,
    archived,
    open_change,
    planning,
    scheduled_changes,
    store_of,
)

BOTH = {
    "e2e_splits": {
        "acp": {"marker": "runtime_acp"},
        "claude_code": {"marker": "runtime_claude_code"},
    }
}


def changes_of(repo: str, *names: str, day: date = TODAY) -> list[str]:
    return sorted(scheduled_name(repo, day, name) for name in names)


def round_of(inst: Installation, store, *, today: date = TODAY) -> tuple[list[str], list[str]]:
    said: list[str] = []
    return write_due(inst, store, today=today, say=said.append), said


def written_changes(tmp_path: Path, **kwargs) -> tuple[Installation, list[str]]:
    inst = planning(tmp_path, **kwargs)
    written, _ = round_of(inst, store_of(inst, "app"))
    return inst, written


# --- one change per split ---------------------------------------------------------


def test_a_due_repo_gets_a_change_per_declared_split_and_rest(tmp_path: Path) -> None:
    inst, written = written_changes(tmp_path, tests=BOTH)

    expected = changes_of("app", "rest", "acp", "claude_code")
    assert expected == [
        f"scheduled-e2e-app-{TODAY.isoformat()}-{split}" for split in ("acp", "claude_code", "rest")
    ]
    assert sorted(written) == expected
    assert scheduled_changes(inst) == expected


def test_a_repo_declaring_no_split_gets_only_the_rest_change(tmp_path: Path) -> None:
    inst, written = written_changes(tmp_path)

    assert written == [f"scheduled-e2e-app-{TODAY.isoformat()}-rest"]
    assert scheduled_changes(inst) == written


def test_off_writes_none_for_its_repo_while_a_neighbour_writes_its_splits(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path, {"app": "off", "platform": None}, tests=BOTH)
    store = store_of(inst, "app", "platform")

    written, _ = round_of(inst, store)

    assert sorted(written) == changes_of("platform", "rest", "acp", "claude_code")
    assert not any("-app-" in name for name in scheduled_changes(inst))


def test_a_repos_own_splits_are_used_instead_of_the_top_level_map(tmp_path: Path) -> None:
    inst = planning(
        tmp_path,
        {"app": None, "platform": None},
        tests={"e2e_splits": {"acp": {"marker": "runtime_acp"}}},
        repo_splits={"app": {"claude_code": {"marker": "runtime_claude_code"}}, "platform": {}},
    )
    store = store_of(inst, "app", "platform")

    written, _ = round_of(inst, store)

    assert sorted(written) == sorted(
        changes_of("app", "rest", "claude_code") + changes_of("platform", "rest")
    )


# --- due, per split ---------------------------------------------------------------


def test_a_split_never_run_is_due_at_once_while_the_others_wait(tmp_path: Path) -> None:
    inst = planning(tmp_path, tests=BOTH)
    store = store_of(inst, "app")
    archived(inst, "app", ago(3), "rest")
    archived(inst, "app", ago(3), "claude_code")

    written, _ = round_of(inst, store)

    assert written == changes_of("app", "acp")
    assert scheduled_changes(inst) == written


def test_the_latest_archived_change_of_the_split_sets_its_due_date(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path, tests=BOTH)
    store = store_of(inst, "app")
    archived(inst, "app", ago(40), "acp")
    archived(inst, "app", ago(3), "acp")
    archived(inst, "app", ago(8), "rest")
    archived(inst, "app", ago(8), "claude_code")

    written, _ = round_of(inst, store)

    assert sorted(written) == changes_of("app", "rest", "claude_code")


def test_a_name_with_no_suffix_or_ending_base_reads_as_rest(tmp_path: Path) -> None:
    inst = planning(tmp_path, tests=BOTH)
    store = store_of(inst, "app")
    day = ago(3).isoformat()
    for older in (f"{PREFIX}-app-{day}", f"{PREFIX}-app-{day}-base"):
        (inst.changes_dir / "archive" / f"{day}-{older}").mkdir(parents=True)

    written, _ = round_of(inst, store)

    assert sorted(written) == changes_of("app", "acp", "claude_code")


def test_the_date_and_split_are_read_from_the_name_of_exactly_that_repo_and_split() -> None:
    cases = [
        ("scheduled-e2e-app-2026-03-10", "app", (TODAY, "rest")),
        ("scheduled-e2e-app-2026-03-10-base", "app", (TODAY, "rest")),
        ("scheduled-e2e-app-2026-03-10-rest", "app", (TODAY, "rest")),
        ("scheduled-e2e-app-2026-03-10-acp", "app", (TODAY, "acp")),
        ("scheduled-e2e-app-2026-03-10-claude_code", "app", (TODAY, "claude_code")),
        ("scheduled-e2e-app-web-2026-03-10-acp", "app-web", (TODAY, "acp")),
        ("scheduled-e2e-app-web-2026-03-10", "app-web", (TODAY, "rest")),
        ("scheduled-e2e-app-web-2026-03-10-acp", "app", None),
        ("scheduled-e2e-app-2026-03-10-acp", "app-web", None),
        ("scheduled-e2e-app-2026-03-10-acp_two", "app", None),
        ("scheduled-e2e-app-2026-03-10-other", "app", None),
        ("scheduled-e2e-app-2026-13-40-acp", "app", None),
        ("fix-failing-app-2026-03-10-acp", "app", None),
    ]

    for name, repo, expected in cases:
        assert scheduled_parts(name, repo, ["acp", "claude_code", "rest"]) == expected, name


def test_a_split_whose_name_begins_another_is_not_confused(tmp_path: Path) -> None:
    inst = planning(
        tmp_path,
        tests={
            "e2e_splits": {
                "acp": {"marker": "runtime_acp"},
                "acp_two": {"marker": "runtime_acp_two"},
            }
        },
    )
    store = store_of(inst, "app")
    archived(inst, "app", ago(1), "acp_two")
    open_change(inst, "app", ago(1), "rest")

    written, said = round_of(inst, store)

    # acp_two ran yesterday, which says nothing of acp; rest is open and acp_two is not.
    assert written == changes_of("app", "acp")
    assert said == [f"wrote: {written[0]}", f"exists: {scheduled_name('app', ago(1), 'rest')}"]


def test_a_repo_whose_name_begins_another_does_not_share_its_splits(tmp_path: Path) -> None:
    inst = planning(
        tmp_path,
        {"app": None, "app-web": None},
        tests={"e2e_splits": {"acp": {"marker": "runtime_acp"}}},
    )
    store = store_of(inst, "app", "app-web")
    archived(inst, "app-web", ago(1), "rest")
    archived(inst, "app-web", ago(1), "acp")

    written, _ = round_of(inst, store)

    assert sorted(written) == changes_of("app", "rest", "acp")


def test_nothing_is_stored_but_the_change_names(tmp_path: Path) -> None:
    inst = planning(tmp_path, tests=BOTH)
    store = store_of(inst, "app")
    before = {p.name for p in inst.state_dir.iterdir()}

    written, _ = round_of(inst, store)

    assert len(written) == 3
    assert {p.name for p in inst.state_dir.iterdir()} <= before | {"scheduled-e2e.lock"}
    (inst.changes_dir / "archive").mkdir()
    for name in written:
        (inst.changes_dir / name).rename(inst.changes_dir / "archive" / f"2026-04-20-{name}")
    assert round_of(inst, store, today=TODAY + timedelta(days=6))[0] == []
    seventh = TODAY + timedelta(days=7)
    assert sorted(round_of(inst, store, today=seventh)[0]) == changes_of(
        "app", "rest", "acp", "claude_code", day=seventh
    )


# --- one open at a time, per split ------------------------------------------------


def test_no_second_change_is_written_for_a_split_while_one_is_open(tmp_path: Path) -> None:
    inst = planning(tmp_path, tests=BOTH)
    store = store_of(inst, "app")
    existing = open_change(inst, "app", ago(60), "acp")

    written, said = round_of(inst, store)

    assert sorted(written) == changes_of("app", "rest", "claude_code")
    assert f"exists: {existing}" in said
    assert scheduled_changes(inst) == sorted([existing, *written])


def test_five_missed_periods_write_one_change_per_split_and_a_second_round_none(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path, tests=BOTH)
    store = store_of(inst, "app")
    for split in ("rest", "acp", "claude_code"):
        archived(inst, "app", ago(35), split)

    first, _ = round_of(inst, store)
    second, said = round_of(inst, store)

    assert sorted(first) == changes_of("app", "rest", "acp", "claude_code")
    assert second == []
    assert scheduled_changes(inst) == sorted(first)
    assert sorted(said[-3:]) == sorted(f"exists: {name}" for name in first)


def test_two_writers_at_once_write_one_change_per_split(tmp_path: Path) -> None:
    inst = planning(tmp_path, tests=BOTH)
    store = store_of(inst, "app")
    meeting = threading.Barrier(2)
    results: list[tuple[list[str], list[str]]] = []

    def write() -> None:
        meeting.wait()
        results.append(round_of(inst, store))

    writers = [threading.Thread(target=write) for _ in range(2)]
    for writer in writers:
        writer.start()
    for writer in writers:
        writer.join(timeout=30)

    expected = changes_of("app", "rest", "acp", "claude_code")
    assert scheduled_changes(inst) == expected
    assert sorted(name for wrote, _ in results for name in wrote) == expected


# --- what is written ----------------------------------------------------------------


def test_each_change_names_its_split_and_has_one_group_at_priority_3(tmp_path: Path) -> None:
    inst, written = written_changes(tmp_path, tests=BOTH)

    assert len(written) == 3
    for name in written:
        split = name.removeprefix(f"{PREFIX}-app-{TODAY.isoformat()}-")
        change = inst.changes_dir / name
        for document in ("proposal.md", "design.md", "tasks.md"):
            assert split in (change / document).read_text(), (name, document)
        groups, errors = validate_tasks(change / "tasks.md", repos=tuple(inst.repos))
        assert errors == []
        [group] = groups
        assert (group.repo, group.tier, group.priority) == ("app", "e2e-test", 3)
        assert group.separate
        assert any(
            line.startswith("Separate:") for line in (change / "tasks.md").read_text().splitlines()
        )
        assert cli.cmd_tags(argparse.Namespace(all=False, change=name), inst) == 0


def test_a_held_splits_change_is_written_like_the_others_and_stays_open(
    tmp_path: Path,
) -> None:
    held = {**BOTH["e2e_splits"], "acp": {"marker": "runtime_acp", "hold": True}}
    inst = planning(tmp_path, tests={"e2e_splits": held})
    store = store_of(inst, "app")

    first, _ = round_of(inst, store)
    second, said = round_of(inst, store)

    assert sorted(first) == changes_of("app", "rest", "acp", "claude_code")
    assert second == []
    assert scheduled_name("app", TODAY, "acp") in scheduled_changes(inst)
    assert f"exists: {scheduled_name('app', TODAY, 'acp')}" in said
