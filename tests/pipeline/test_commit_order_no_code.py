"""The commit-order check and the progress walk follow each group's build mode: a `no_code` group
takes a lone `feat:` or an optional `test:` then `feat:` pair, a `refactor` group a lone `feat:`,
and a unit mixing modes is checked group by group (spec: group-build-modes)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.commit_order import (
    GroupProgress,
    adopted_subject,
    check_structure,
    group_progress,
    superseded_pairs,
)
from tests.factories import commit_files
from tests.stub_gate_support import (
    commit_docs,
    commit_feat,
    commit_tests,
    modes,
    plan_modes,
    repo,  # noqa: F401  (the fixture)
)

CODE = "tests_and_code"


def test_a_lone_feat_of_a_no_code_group_passes(repo: Path) -> None:  # noqa: F811 — fixture
    commit_docs(repo, "Docs", "guide")

    problems = check_structure(repo, "main", paired=True, groups=plan_modes(("Docs", "no_code")))

    assert problems == []


def test_a_no_code_group_beside_a_pair_is_checked_on_its_own(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_docs(repo, "Docs", "guide")

    problems = check_structure(
        repo, "main", paired=True, groups=plan_modes(("A", CODE), ("Docs", "no_code"))
    )

    assert problems == []


def test_a_no_code_group_may_add_a_test_then_a_feat(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "Docs", "docs")
    commit_docs(repo, "Docs", "guide")

    problems = check_structure(repo, "main", paired=True, groups=plan_modes(("Docs", "no_code")))

    assert problems == []


def test_a_lone_feat_of_a_refactor_group_passes(repo: Path) -> None:  # noqa: F811 — fixture
    commit_feat(repo, "Move", "moved")

    problems = check_structure(repo, "main", paired=True, groups=plan_modes(("Move", "refactor")))

    assert problems == []


def test_a_refactor_group_beside_a_pair_is_checked_on_its_own(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_feat(repo, "Move", "moved")

    problems = check_structure(
        repo, "main", paired=True, groups=plan_modes(("A", CODE), ("Move", "refactor"))
    )

    assert problems == []


def test_a_lone_tests_commit_of_a_tests_only_group_still_passes_beside_a_no_code_group(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    commit_docs(repo, "Docs", "guide")
    commit_tests(repo, "Drive", "drive")

    problems = check_structure(
        repo, "main", paired=True, groups=plan_modes(("Docs", "no_code"), ("Drive", "tests_only"))
    )

    assert problems == []


def test_the_walk_takes_a_lone_feat_for_a_no_code_or_refactor_group() -> None:
    titles = ["A", "Docs", "Move"]

    done = group_progress(
        ["test: A", "feat: A", "feat: Docs", "feat: Move"],
        titles,
        modes(CODE, "no_code", "refactor"),
    )

    assert done == GroupProgress(done=3, tests_made=False)


def test_the_walk_takes_a_no_code_groups_pair_too() -> None:
    progress = group_progress(
        ["test: Docs", "feat: Docs", "feat: Move"], ["Docs", "Move"], modes("no_code", "refactor")
    )

    assert progress == GroupProgress(done=2, tests_made=False)


def test_the_walk_reports_a_lone_feat_only_for_a_code_group() -> None:
    subjects = ["test: A", "feat: A", "feat: B"]

    code = group_progress(subjects, ["A", "B"], modes(CODE, CODE))
    no_code = group_progress(subjects, ["A", "B"], modes(CODE, "no_code"))

    assert code == GroupProgress(done=1, tests_made=False, lone_feat="feat: B")
    assert no_code == GroupProgress(done=2, tests_made=False)


def test_the_walk_still_takes_a_tests_only_groups_lone_test_commit() -> None:
    progress = group_progress(
        ["feat: Docs", "test: Drive"], ["Docs", "Drive"], modes("no_code", "tests_only")
    )

    assert progress == GroupProgress(done=2, tests_made=False)


def test_the_commit_an_adoption_becomes_follows_the_mode_reached() -> None:
    steps = plan_modes(("A", CODE), ("Docs", "no_code"), ("C", CODE))

    after_docs = adopted_subject("Unit", steps, ["test: A", "feat: A", "feat: Docs"])

    assert after_docs == "test: C"


def test_the_commits_of_a_superseded_unit_are_split_one_for_a_lone_feat_group(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    first = commit_tests(repo, "A", "a")
    second = commit_feat(repo, "A", "a")
    third = commit_docs(repo, "Docs", "guide")

    found = superseded_pairs(
        repo,
        "HEAD",
        "main",
        ["A", "Docs"],
        modes(CODE, "no_code"),
    )

    assert found == [[first, second], [third]]


def test_a_tests_only_groups_commit_of_code_alone_is_refused(repo: Path) -> None:  # noqa: F811 — fixture
    commit_files(repo, "test: T", {"src/x.py": "x = 1\n"})

    problems = check_structure(repo, "main", paired=True, groups=plan_modes(("T", "tests_only")))

    assert any("first commit contains implementation" in problem for problem in problems), problems


def test_a_tests_only_groups_commit_of_a_document_alone_is_refused(repo: Path) -> None:  # noqa: F811 — fixture
    commit_files(repo, "test: T", {"README.md": "words\n"})

    problems = check_structure(repo, "main", paired=True, groups=plan_modes(("T", "tests_only")))

    assert any("changes no tests and no code" in problem for problem in problems), problems


def test_a_refactors_lone_feat_may_edit_tests_beside_code_with_a_body(repo: Path) -> None:  # noqa: F811 — fixture
    commit_files(
        repo,
        "feat: Move",
        {"src/n.py": "def n():\n    return 1\n", "tests/test_m.py": "def test_m(): assert True\n"},
    )

    problems = check_structure(repo, "main", paired=True, groups=plan_modes(("Move", "refactor")))

    assert problems == []


def test_a_tests_commit_for_a_refactor_group_is_refused(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "Move", "m")
    commit_feat(repo, "Move", "moved")

    problems = check_structure(repo, "main", paired=True, groups=plan_modes(("Move", "refactor")))

    assert any("test: Move" in problem and "reorganization" in problem for problem in problems)


def test_a_refactor_group_is_told_from_an_earlier_group_with_its_title_by_position(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    commit_tests(repo, "Move", "m")
    commit_feat(repo, "Move", "moved")
    commit_feat(repo, "Move", "moved_again")

    problems = check_structure(
        repo, "main", paired=True, groups=plan_modes(("Move", CODE), ("Move", "refactor"))
    )

    assert problems == []
