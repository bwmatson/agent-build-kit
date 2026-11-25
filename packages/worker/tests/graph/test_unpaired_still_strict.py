"""A commit whose subject does not follow the convention is not counted toward a group's pair,
whether it was made by hand or adopted as it was: the stop for a missing pair still raises, and
the subject the pipeline would give the next adopted commit is still the group's own (spec:
attach-commit-subject)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.commit_order import adopted_subject
from agent_build_kit.pipeline.stack_runner import GroupStep
from packages.worker.tests.graph.test_build_path import build
from tests.graph.branch_fakes import (
    TRAILER,
    built_after_a_pair,
    messages,
    prepared,
    subjects,
    titled,
)

HAND_MADE = "Release the unit after the config edit"
OLD_TITLE = "test: The earlier title of group 3"
PAIR = "the branch holds no tests and implementation pair for group 3 (G3)"


def test_a_hand_made_commit_with_a_free_text_subject_is_not_counted_and_the_stop_raises(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(
        tmp_path,
        groups={"add-marker": titled(3)},
        seeded=["test: G3", HAND_MADE],
        no_commit_for="3",
        unit_test_ok=False,
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert PAIR in outcome.detail
    assert subjects(repo) == ["test: G3", HAND_MADE]
    group = GroupStep(change_dir="changes/add-marker", number=3, title="G3")
    assert adopted_subject("Add the marker", (group,), subjects(repo)) == "feat: G3", (
        "the free-text commit is not counted, and a feat: adopted after it cannot pair across it "
        "either: the stop still raises"
    )


def test_every_commit_a_stubbed_build_makes_for_a_group_carries_the_groups_trailer(
    tmp_path: Path,
) -> None:
    """Group 3 is built by real tests and implementation commits, group 4 by an empty recorded-built
    pair, and each carries `Group: <change>/<number>` beside `Unit:`."""
    _, outcome, repo = built_after_a_pair(tmp_path)

    assert outcome.status != "failed", outcome.detail
    made = messages(repo)
    assert len(made) == 4
    for message, number in zip(made, (3, 3, 4, 4), strict=True):
        assert TRAILER in message
        assert f"Group: add-marker/{number}" in message.splitlines(), message


def test_the_stop_names_the_subject_found_at_the_groups_place(tmp_path: Path) -> None:
    recorder, repo = prepared(
        tmp_path,
        groups={"add-marker": titled(3)},
        seeded=[OLD_TITLE],
        no_commit_for="3",
        unit_test_ok=False,
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert PAIR in outcome.detail
    assert OLD_TITLE in outcome.detail, "the stop names what stands where group 3's tests belong"
