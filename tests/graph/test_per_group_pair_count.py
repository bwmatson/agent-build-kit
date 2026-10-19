"""After the last group a stubbed build counts the pairs on the branch against the groups, and a
count short of them stops the unit naming the groups missing (spec: per-group-commits). Each case
is built beside the one it is told from, so it fails while the count is not checked."""

from __future__ import annotations

from pathlib import Path

from tests.graph.branch_fakes import built, subjects

TITLES = {1: ("Parse the key", ""), 2: ("Use the key", ""), 3: ("Drop the key", "")}
GROUPS = {"add-marker": TITLES}


def test_a_last_implementation_that_made_no_commit_stops_the_unit_naming_the_group(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, groups=GROUPS, no_commit_for="3")

    assert outcome.status == "failed"
    assert "Drop the key" in outcome.detail or "group 3" in outcome.detail
    assert subjects(repo)[-1] == "test: Drop the key", "the pair of the third group is short"
    assert "review" not in recorder.events, "nothing is reviewed"
    assert "unit-test" not in recorder.events


def test_a_full_count_goes_on_to_the_checks_and_a_short_one_does_not(tmp_path: Path) -> None:
    short, stopped, _ = built(tmp_path / "short", groups=GROUPS, no_commit_for="3")
    full, outcome, repo = built(tmp_path / "full", groups=GROUPS)

    assert stopped.status == "failed"
    assert outcome.status == "open"
    assert len(subjects(repo)) == 6
    assert full.events.index("unit-test") > full.events.index("commit:feat")
    assert "review" in full.events and "review" not in short.events


def test_a_unit_that_is_not_stubbed_is_counted_as_before(tmp_path: Path) -> None:
    stubbed, stopped, _ = built(tmp_path / "stubbed", groups=GROUPS, no_commit_for="3")
    plain, outcome, repo = built(
        tmp_path / "plain", groups=GROUPS, setting=False, no_commit_for="1, 2, 3"
    )

    assert stopped.status == "failed", "the same silence, counted per group, stops the unit"
    assert outcome.status == "open", "one pair for the unit, and its tests commit is work enough"
    assert subjects(repo) == ["test: Register the marker"]
    assert "review" in plain.events
