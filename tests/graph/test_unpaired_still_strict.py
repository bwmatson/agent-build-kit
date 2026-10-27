"""A commit whose subject does not follow the convention is not counted toward a group's pair,
whether it was made by hand or adopted as it was: the stop for a missing pair still raises, and
the subject the pipeline would give the next adopted commit is still the group's own (spec:
attach-commit-subject)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.commit_order import adopted_subject
from agent_build_kit.pipeline.stack_runner import GroupStep
from tests.graph.branch_fakes import prepared, subjects, titled
from tests.graph.test_build_path import build

HAND_MADE = "Release the unit after the config edit"
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
        "the free-text commit does not stand in for the group's implementation"
    )
