"""`abk attach release --commit MESSAGE` makes a commit whose subject the pipeline builds from the
unit's group progress and whose body is MESSAGE, and says which subject it used (spec:
attach-commit-subject)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.installation import Installation
from tests.stubbed_attach import (
    TITLE,
    UNIT,
    dirty_tree,
    groups_paired,
    last_body,
    last_subject,
    stubbed_installation,
)

MESSAGE = "Release after the config edit"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = stubbed_installation(tmp_path)
    monkeypatch.chdir(installation.root)
    return installation


def test_implementation_adopted_after_the_tests_commit_is_the_groups_feat_and_pairs_it(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    tree = dirty_tree(inst, f"test: {TITLE}")

    assert main(["attach", "release", UNIT, "--commit", MESSAGE]) == 0

    assert last_subject(tree) == f"feat: {TITLE}"
    assert MESSAGE in last_body(tree)
    assert f"feat: {TITLE}" in capsys.readouterr().out, "the command says which subject it used"
    assert groups_paired(tree, [TITLE]) == 1, "the unit has its pair for the group"


def test_tests_adopted_on_a_fresh_branch_are_the_groups_tests_commit(inst: Installation) -> None:
    tree = dirty_tree(inst)

    assert main(["attach", "release", UNIT, "--commit", MESSAGE]) == 0

    assert last_subject(tree) == f"test: {TITLE}"
    assert MESSAGE in last_body(tree)


def test_work_adopted_when_every_group_has_its_commits_is_a_fix_naming_the_last_group(
    inst: Installation,
) -> None:
    tree = dirty_tree(inst, f"test: {TITLE}", f"feat: {TITLE}")

    assert main(["attach", "release", UNIT, "--commit", MESSAGE]) == 0

    assert last_subject(tree) == f"fix: {TITLE} (adopted)"
    assert MESSAGE in last_body(tree)
    assert groups_paired(tree, [TITLE]) == 1
