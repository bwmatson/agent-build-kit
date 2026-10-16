"""A scheduled change written under the kind's old spelling is still a scheduled change."""

from pathlib import Path

from agent_build_kit.pipeline.e2e_schedule import (
    any_due,
    is_scheduled,
    scheduled_name,
    scheduled_parts,
    write_due,
)
from tests.tier2_schedule_fakes import TODAY, planning, store_of


def test_the_old_and_the_new_prefix_both_mark_a_scheduled_change() -> None:
    assert is_scheduled("scheduled-tier2-app-2026-03-10-rest")
    assert is_scheduled("scheduled-e2e-app-2026-03-10-rest")


def test_an_ordinary_change_is_not_scheduled() -> None:
    assert not is_scheduled("feature")


def test_the_old_name_gives_the_same_date_and_split_as_the_new_one() -> None:
    old = scheduled_parts("scheduled-tier2-app-2026-03-10-acp", "app", ("acp", "rest"))
    new = scheduled_parts("scheduled-e2e-app-2026-03-10-acp", "app", ("acp", "rest"))

    assert old == new == (TODAY, "acp")


def test_a_repo_whose_name_holds_an_old_spelling_reads_back_as_written() -> None:
    name = scheduled_name("tier2-api", TODAY, "rest")

    assert scheduled_parts(name, "tier2-api", ("rest",)) == (TODAY, "rest")
    assert is_scheduled(name)


def test_the_old_prefix_over_such_a_repo_reads_the_same() -> None:
    name = f"scheduled-tier2-tier2-api-{TODAY.isoformat()}-rest"

    assert scheduled_parts(name, "tier2-api", ("rest",)) == (TODAY, "rest")
    assert is_scheduled(name)


def test_a_split_whose_name_holds_an_old_spelling_is_kept() -> None:
    name = scheduled_name("app", TODAY, "tier1")

    assert scheduled_parts(name, "app", ("tier1", "rest")) == (TODAY, "tier1")


def test_an_open_old_named_change_makes_a_round_say_it_exists_and_write_nothing(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")
    old = f"scheduled-tier2-app-{TODAY.isoformat()}-rest"
    (inst.changes_dir / old).mkdir(parents=True)
    said: list[str] = []

    written = write_due(inst, store, today=TODAY, say=said.append)

    assert written == []
    assert said == [f"exists: {old}"]
    assert [p.name for p in inst.changes_dir.iterdir()] == [old]


def test_an_archived_old_named_change_dated_today_leaves_the_split_not_due(
    tmp_path: Path,
) -> None:
    inst = planning(tmp_path)
    store = store_of(inst, "app")
    old = f"scheduled-tier2-app-{TODAY.isoformat()}-rest"
    (inst.changes_dir / "archive" / f"{TODAY.isoformat()}-{old}").mkdir(parents=True)

    assert write_due(inst, store, today=TODAY, say=lambda line: None) == []
    assert not any_due(inst, store, today=TODAY)
