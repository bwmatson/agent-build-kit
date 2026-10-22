"""The empty `test:` of a group with no new tests is made only for a not-test-only group of a
stubbed unit whose branch has a commit of its own, whose tests agent committed nothing, whose
static checks pass and whose branch holds no lone `feat:` of the group; every other case is as
it was (spec: built-group-recorded-as-empty-pair). Each case is built beside the one that makes
the commit, so the file fails while nothing is made."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.units import SATISFIED
from tests.graph.branch_fakes import UNIT, built, messages, prepared, subjects, titled
from tests.graph.test_build_path import build

GROUPS = {"add-marker": titled(3, 4)}
PAIR_3 = ["test: G3", "feat: G3"]
LONE = "a feat: commit for group 4 has no test: commit before it (feat: G4)"
OUTPUT = "E   F401 `os` imported but unused"


def made_beside(tmp_path: Path) -> None:
    """The same unit with a tests agent that commits nothing, which makes the empty `test:`."""
    recorder, outcome, repo = built(tmp_path / "beside", groups=GROUPS, no_tests_for="4")
    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"]
    assert recorder.events.count("commit_built:test") == 1


def test_a_branch_with_no_commit_of_its_own_is_satisfied_and_gets_no_empty_test_commit(
    tmp_path: Path,
) -> None:
    made_beside(tmp_path)
    recorder, outcome, repo = built(tmp_path / "zero", silent_groups=(1, 2, 3))

    assert outcome.status == "satisfied"
    assert recorder.store.get(UNIT).state == SATISFIED
    assert subjects(repo) == []
    assert "commit_built:test" not in recorder.events


def test_a_test_only_group_keeps_its_earlier_tests_commit_and_gets_no_second_one(
    tmp_path: Path,
) -> None:
    made_beside(tmp_path)
    recorder, outcome, repo = built(
        tmp_path / "test-only", groups=GROUPS, e2e=(4,), silent_groups=(4,)
    )

    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == [*PAIR_3, "test: G4"], "its own empty tests commit, no feat:"
    assert recorder.events.count("commit_built:test") == 1
    assert "commit_built:feat" not in recorder.events


def test_a_group_whose_tests_agent_committed_gets_no_empty_test_commit(tmp_path: Path) -> None:
    made_beside(tmp_path)
    recorder, _, repo = built(tmp_path / "committed", groups=GROUPS)

    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"]
    assert not any("Already-built" in message for message in messages(repo))
    assert "commit_built:test" not in recorder.events


def test_with_the_setting_off_no_empty_test_commit_is_made(tmp_path: Path) -> None:
    made_beside(tmp_path)
    recorder, _, repo = built(tmp_path / "off", setting=False, groups=GROUPS, no_tests_for="4")

    assert not any("Already-built" in message for message in messages(repo))
    assert not [event for event in recorder.events if event.startswith("commit_built")]


def test_a_lone_feat_commit_of_the_group_stops_the_unit_and_no_empty_test_commit_is_made(
    tmp_path: Path,
) -> None:
    made_beside(tmp_path)
    recorder, repo = prepared(
        tmp_path / "lone",
        groups=GROUPS,
        seeded=[*PAIR_3, "feat: G4"],
        silent_groups=(4,),
    )

    outcome = build(tmp_path / "lone", recorder, **recorder.overrides(tmp_path / "lone"))

    assert outcome.status == "failed"
    assert LONE in outcome.detail
    assert subjects(repo) == [*PAIR_3, "feat: G4"]
    assert "commit_built:test" not in recorder.events


def test_failing_static_checks_make_no_empty_test_commit_until_they_pass(tmp_path: Path) -> None:
    made_beside(tmp_path)
    mended, _, repo = built(
        tmp_path / "mended",
        groups=GROUPS,
        no_tests_for="4",
        checks=[(True, ""), (False, OUTPUT), (True, "")],
    )

    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"]
    assert mended.events.index("claude:fix_stub") < mended.events.index("commit_built:test")

    failing, outcome, repo = built(
        tmp_path / "failing",
        groups=GROUPS,
        no_tests_for="4",
        checks=[(True, ""), (False, OUTPUT)],
    )

    assert outcome.status == "failed"
    assert subjects(repo) == PAIR_3
    assert "commit_built:test" not in failing.events
