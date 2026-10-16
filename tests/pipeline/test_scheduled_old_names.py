"""A scheduled change written under the kind's old spelling is still a scheduled change."""

from agent_build_kit.pipeline.e2e_schedule import is_scheduled, scheduled_name, scheduled_parts
from tests.tier2_schedule_fakes import TODAY


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
