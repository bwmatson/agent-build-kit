"""The table of spellings lists, for each forbidden class, the spellings the
design names (`tests/runtimes/test_acp_probe_classes.py` holds the check's list to the table).
"""

from __future__ import annotations

from agent_build_kit.pipeline.command_spellings import SPELLINGS, Reader, probe_rows
from tests.spelling_rows import (
    AMEND,
    BRANCH_DELETE,
    FORCE_PUSH,
    HARD_RESET,
    MERGE,
    PUSH,
    RAW_MERGE,
    WRAPPERS,
)

GIT_OPTIONS = {
    "plain": "git",
    "directory": "git -C .",
    "config": "git -c core.editor=true",
    "no-pager": "git --no-pager",
    "git-dir": "git --git-dir=.git",
    "work-tree": "git --work-tree=.",
    "combined": "git -C . -c k=v --no-pager",
}

GIT_CLASSES = {
    AMEND: "commit --amend --no-edit",
    PUSH: "push origin main",
    FORCE_PUSH: "push --force origin +main",
}


def probed(label: str) -> list[tuple[str, str]]:
    return [
        (spelling.name.value, spelling.command)
        for row_label, spelling in probe_rows()
        if row_label == label
    ]


def test_each_git_class_is_probed_with_every_global_option_spelling() -> None:
    for label, tail in GIT_CLASSES.items():
        assert probed(label) == [(name, f"{prefix} {tail}") for name, prefix in GIT_OPTIONS.items()]


def test_a_merge_is_probed_plain_and_with_each_repository_option() -> None:
    assert probed(MERGE) == [
        ("plain", "gh pr merge 1"),
        ("repo", "gh -R o/r pr merge 1"),
        ("repo-long", "gh --repo o/r pr merge 1"),
    ]


def test_a_raw_api_merge_is_probed_with_the_method_either_side_of_the_path() -> None:
    assert probed(RAW_MERGE) == [
        ("api-put", "gh api -X PUT repos/o/r/pulls/1/merge"),
        ("api-method-after", "gh api repos/o/r/pulls/1/merge -X PUT"),
    ]


def test_the_judge_also_reads_the_two_word_forms_and_the_landings() -> None:
    judged = {
        label: {spelling.name.value: spelling.command for spelling in spellings}
        for label, spellings in SPELLINGS.items()
    }
    assert judged[AMEND]["git-dir-separate"] == "git --git-dir .git commit --amend --no-edit"
    assert judged[AMEND]["work-tree-separate"] == "git --work-tree . commit --amend --no-edit"
    assert judged[PUSH]["refspec"] == "git --no-pager push origin HEAD:main"
    assert judged[PUSH]["master"] == "git -C . push origin master"
    assert judged[MERGE]["repo-equals"] == "gh --repo=o/r pr merge 1"
    assert judged[RAW_MERGE]["api-method"] == "gh api --method PUT repos/o/r/pulls/1/merge"
    assert judged[RAW_MERGE]["api-query"] == (
        "gh api -X PUT repos/o/r/pulls/1/merge?merge_method=squash"
    )
    assert judged[RAW_MERGE]["api-trailing-slash"] == "gh api repos/o/r/pulls/1/merge/ -X PUT"
    assert judged[HARD_RESET]["directory"] == "git -C . reset --hard"
    assert judged[BRANCH_DELETE]["directory"] == "git -C . branch -D x"


def test_the_wrapper_rows_are_for_the_judge_only() -> None:
    for label in (AMEND, MERGE):
        wrappers = [s for s in SPELLINGS.get(label, ()) if s.name in WRAPPERS]
        assert {s.name for s in wrappers} == WRAPPERS, label
        assert all(s.readers == {Reader.JUDGE} for s in wrappers), label
        assert sum(s.command.startswith("sudo -u root ") for s in wrappers) == 1, label
