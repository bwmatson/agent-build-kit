"""The push gate runs a red check at a tests commit of a `tests_and_code` group alone: the commit
of a `no_code` pair, the lone `feat:` of a `no_code` or `refactor` group and the lone commit of a
`tests_only` group get none (spec: group-build-modes).

Over real git repositories, with the toolchain's commands scripted by `RedProfile`.
"""

from __future__ import annotations

from pathlib import Path

from tests.pipeline.test_gate_test_only import RedProfile
from tests.stub_gate_support import (
    commit_docs,
    commit_feat,
    commit_tests,
    judged,
    plan_modes,
    repo,  # noqa: F401  (the fixture)
)

PASSING = "def test_x(): assert True\n"


def test_the_tests_commit_of_a_no_code_pair_gets_no_red_run(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "Docs", "pass", PASSING)
    commit_docs(repo, "Docs", "guide")
    profile = RedProfile()

    problems = judged(repo, profile, stubbed=True, groups=plan_modes(("Docs", "no_code")))

    assert problems == []
    assert profile.red_files == []
    assert profile.cleans == [True]


def test_a_lone_feat_of_a_no_code_group_is_gated_with_no_red_run(repo: Path) -> None:  # noqa: F811 — fixture
    commit_docs(repo, "Docs", "guide")
    profile = RedProfile()

    problems = judged(repo, profile, stubbed=True, groups=plan_modes(("Docs", "no_code")))

    assert problems == []
    assert profile.red_files == []


def test_a_lone_feat_of_a_refactor_group_is_gated_with_no_red_run(repo: Path) -> None:  # noqa: F811 — fixture
    commit_feat(repo, "Move", "moved")
    profile = RedProfile()

    problems = judged(repo, profile, stubbed=True, groups=plan_modes(("Move", "refactor")))

    assert problems == []
    assert profile.red_files == []


def test_a_unit_that_mixes_modes_is_gated_group_by_group(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_docs(repo, "Docs", "guide")
    commit_feat(repo, "Move", "moved")
    profile = RedProfile()

    problems = judged(
        repo,
        profile,
        stubbed=True,
        groups=plan_modes(("A", "tests_and_code"), ("Docs", "no_code"), ("Move", "refactor")),
    )

    assert problems == []
    assert profile.red_files == [["tests/test_a.py"]]
