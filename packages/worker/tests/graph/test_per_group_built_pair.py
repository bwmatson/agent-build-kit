"""A stubbed unit with commits of its own records a group its agents left nothing to commit
for, with an empty pair marked `Already-built: yes`, once the whole repository's unit tests pass
(spec: built-group-recorded-as-empty-pair). The branch is real; each negative case is built
beside a recorded one, so the file fails while nothing is recorded."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.units import SATISFIED
from tests.graph.branch_fakes import (
    ACCOUNT,
    UNIT,
    built,
    built_after_a_pair,
    messages,
    recorded_pair,
    subjects,
    titled,
)

HEADING = "Already built, the builder's account:"


def account_in(message: str) -> str:
    """The account a recorded `feat:` commit's body holds, without the trailers after it."""
    return message.split(HEADING, 1)[1].rsplit("\n\n", 1)[0].strip()


def test_group_4_already_built_after_group_3s_pair_is_recorded_with_an_empty_marked_pair(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built_after_a_pair(tmp_path)

    assert outcome.status == "open", outcome.detail
    recorded_pair(repo)
    assert account_in(messages(repo)[-1]) == ACCOUNT
    assert recorder.events.count("unit-test:whole_repo") == 1
    for step in ("unit-test", "review"):
        assert step in recorder.events, "the unit goes on to the checks and the review"
    assert recorder.store.get(UNIT).state != SATISFIED


def test_a_long_account_is_cut_to_2000_characters_and_a_secret_in_it_is_redacted(
    tmp_path: Path,
) -> None:
    token = "ghp_" + "a1" * 20
    _, _, long = built_after_a_pair(tmp_path / "long", accounts={"4": "word " * 1000})
    _, _, secret = built_after_a_pair(tmp_path / "secret", accounts={"4": f"Used {token} to check"})

    assert 1900 < len(account_in(messages(long)[-1])) <= 2000
    assert token not in messages(secret)[-1]
    assert "Used" in messages(secret)[-1]


def test_a_unit_whose_groups_all_commit_a_pair_records_nothing_and_runs_no_whole_repo_tests(
    tmp_path: Path,
) -> None:
    recorded, _, _ = built_after_a_pair(tmp_path / "recorded")
    plain, outcome, repo = built(tmp_path / "plain", groups={"add-marker": titled(1, 2, 3)})

    assert recorded.events.count("unit-test:whole_repo") == 1
    assert outcome.status == "open"
    assert len(subjects(repo)) == 6
    assert not any("Already-built" in message for message in messages(repo))
    assert "unit-test:whole_repo" not in plain.events


def test_a_first_group_that_made_nothing_with_no_commit_on_the_branch_records_nothing(
    tmp_path: Path,
) -> None:
    recorded, _, _ = built_after_a_pair(tmp_path / "recorded")
    recorder, outcome, repo = built(tmp_path / "first", silent_groups=(1,))

    assert recorded.events.count("unit-test:whole_repo") == 1
    assert outcome.status == "failed"
    assert "pair for group 1" in outcome.detail
    assert subjects(repo) == ["test: G2", "feat: G2"]
    assert not any("Already-built" in message for message in messages(repo))
    assert "unit-test:whole_repo" not in recorder.events
