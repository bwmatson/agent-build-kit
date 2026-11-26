"""A commit whose subject does not follow the convention is not counted toward a group's pair,
whether it was made by hand or adopted as it was: the stop for a missing pair still raises, and
the subject the pipeline would give the next adopted commit is still the group's own (spec:
attach-commit-subject)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.commit_order import adopted_subject
from agent_build_kit.pipeline.stack_runner import GroupStep
from packages.worker.tests.graph.test_build_path import build
from tests.graph.branch_fakes import (
    TRAILER,
    built,
    built_after_a_pair,
    group_trailers,
    land_grouped,
    messages,
    prepared,
    subjects,
    titled,
)

HAND_MADE = "Release the unit after the config edit"
PAIR_4 = "the branch holds no tests and implementation pair for group 4 (G4)"
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
    assert all(TRAILER in message for message in made)
    assert group_trailers(repo) == [f"add-marker/{number}" for number in (3, 3, 4, 4)]


@pytest.mark.parametrize(
    ("seeded", "no_commit_for", "pair", "found"),
    [
        (["test: G3", HAND_MADE], "3", PAIR, "test: G3"),
        # A free-text commit stands where group 4's tests belong: the stop names it. (A seed of
        # an older title at group 3's own place never reaches the stop: the build commits that
        # group's tests after it and goes on, so the place is tested at group 4.)
        (["test: G3", "feat: G3", HAND_MADE], "4", PAIR_4, HAND_MADE),
    ],
)
def test_the_stop_names_the_subject_found_at_the_groups_place(
    tmp_path: Path, seeded: list[str], no_commit_for: str, pair: str, found: str
) -> None:
    recorder, _ = prepared(
        tmp_path,
        groups={"add-marker": titled(3, 4)},
        seeded=seeded,
        no_commit_for=no_commit_for,
        unit_test_ok=False,
    )

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert pair in outcome.detail
    assert f"found `{found}` at its place" in outcome.detail


def test_a_pair_under_an_older_title_is_counted_by_its_trailer_and_the_note_is_said_once(
    tmp_path: Path,
) -> None:
    def earlier(repo: Path) -> None:
        land_grouped(repo, "test: Old G3", "add-marker/3")
        land_grouped(repo, "feat: Old G3", "add-marker/3")

    recorder, outcome, repo = built(
        tmp_path, groups={"add-marker": titled(3, 4)}, meanwhile=earlier
    )

    assert outcome.status != "failed", outcome.detail
    assert subjects(repo) == ["test: Old G3", "feat: Old G3", "test: G4", "feat: G4"]
    said = [line for line in recorder.logged if "Old G3" in line]
    assert len(said) == 1, said
    assert "`test: Old G3`" in said[0]
    assert "`feat: Old G3`" in said[0]
