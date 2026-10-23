"""Audit sampling is deterministic: a hash of the unit and its landed commit against the rate."""

from agent_build_kit.pipeline.audit_sampling import picked

IDS = [f"change-{n}/{n % 7 + 1}" for n in range(1000)]


def commit_of(unit: str) -> str:
    return (unit.encode().hex() * 3)[:40]


def test_a_rate_of_zero_picks_no_unit() -> None:
    assert not any(picked(unit, commit_of(unit), 0) for unit in IDS)


def test_a_rate_of_one_picks_every_unit() -> None:
    assert all(picked(unit, commit_of(unit), 1) for unit in IDS)


def test_the_same_unit_commit_and_rate_always_give_the_same_answer() -> None:
    first = [picked(unit, commit_of(unit), 0.3) for unit in IDS]
    again = [picked(unit, commit_of(unit), 0.3) for unit in IDS]

    assert first == again
    assert any(first), "a rate of 0.3 picks some"


def test_the_commit_is_part_of_what_is_hashed() -> None:
    answers = {picked("feature/1", format(n, "040x"), 0.5) for n in range(200)}

    assert answers == {True, False}


def test_a_rate_of_a_tenth_picks_about_a_tenth_of_a_thousand_ids() -> None:
    count = sum(picked(unit, commit_of(unit), 0.1) for unit in IDS)

    assert 80 <= count <= 120
