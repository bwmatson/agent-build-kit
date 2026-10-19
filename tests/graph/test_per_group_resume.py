"""A stubbed build takes the group it is on from the branch, so a killed run, a restack and a
requeue continue at the first group whose implementation commit is missing (spec:
per-group-commits). The branch is real and starts with the commits an earlier run left."""

from __future__ import annotations

from pathlib import Path

from tests.factories import git
from tests.graph.branch_fakes import BASE, built, subjects
from tests.graph.test_per_group_build import group_named

PAIRS = ["test: G1", "feat: G1", "test: G2", "feat: G2"]
REDATE = "git commit -q --amend --no-edit --date=2001-01-01T00:00:00"
PAIR_STEPS = ["claude:tests", "stub-checks", "commit:test", "claude:impl", "commit:feat"]


def test_two_complete_pairs_of_three_groups_resume_at_the_third_groups_tests(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, seeded=PAIRS)

    assert outcome.status == "open"
    assert recorder.events[:5] == PAIR_STEPS
    assert [group_named(prompt) for prompt in recorder.prompts[:2]] == ["3", "3"]
    assert recorder.subjects == ["test: G3", "feat: G3"], "the first two are not written again"
    assert subjects(repo) == [*PAIRS, "test: G3", "feat: G3"]


def test_a_last_tests_commit_resumes_at_that_groups_implementation(tmp_path: Path) -> None:
    recorder, outcome, repo = built(tmp_path, seeded=[*PAIRS[:2], "test: G2"])

    assert outcome.status == "open"
    assert recorder.events[:2] == ["claude:impl", "commit:feat"], "no tests are written again"
    assert [group_named(prompt) for prompt in recorder.prompts[:3]] == ["2", "3", "3"]
    assert recorder.subjects == ["feat: G2", "test: G3", "feat: G3"]
    assert subjects(repo)[-4:] == ["test: G2", "feat: G2", "test: G3", "feat: G3"]


def test_a_branch_with_every_pair_goes_to_the_checks_and_one_short_of_it_does_not(
    tmp_path: Path,
) -> None:
    short, _, _ = built(tmp_path / "short", seeded=PAIRS)
    full, outcome, repo = built(tmp_path / "full", seeded=[*PAIRS, "test: G3", "feat: G3"])

    assert outcome.status == "open"
    assert not {"claude:tests", "claude:impl"} & set(full.events), "nothing is written"
    assert "unit-test" in full.events and "review" in full.events
    assert len(subjects(repo)) == 6
    assert "claude:tests" in short.events, "the same build, a pair short, writes the group"


def rewrite_every_hash(repo: Path) -> None:
    """What a restack does to a branch: the same commits, each under a new hash."""
    before = git(repo, "rev-list", f"{BASE}..HEAD").split()
    git(repo, "rebase", "-q", "--exec", REDATE, BASE)
    assert not set(before) & set(git(repo, "rev-list", f"{BASE}..HEAD").split())


def test_a_restack_that_rewrote_every_hash_still_resumes_at_the_right_group(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, seeded=PAIRS, meanwhile=rewrite_every_hash)

    assert outcome.status == "open"
    assert recorder.subjects == ["test: G3", "feat: G3"]
    assert subjects(repo)[:4] == PAIRS


def test_a_part_built_branch_with_a_saved_note_continues_at_the_next_group(tmp_path: Path) -> None:
    note = "keep the marker name short"
    recorder, outcome, repo = built(tmp_path, seeded=PAIRS, guidance=note)

    assert outcome.status == "open"
    assert "claude:rework" not in recorder.events
    assert recorder.events[:5] == PAIR_STEPS
    assert group_named(recorder.prompts[0]) == "3"
    assert note in recorder.prompts[0], "the note reaches the group's prompt"
    assert subjects(repo) == [*PAIRS, "test: G3", "feat: G3"]
