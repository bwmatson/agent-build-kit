"""A forbidden command is judged by what it runs, not by how its tool's global
options are spelled.

The spellings are the table's (`command_spellings.SPELLINGS`), so a spelling
added there is judged here with no second edit. Each test loops over a class's
rows and names every row the rules got wrong.
"""

from __future__ import annotations

from agent_build_kit.runtimes.acp import probe_branch
from tests.spelling_rows import (
    AMEND,
    BRANCH_DELETE,
    FORCE_PUSH,
    HARD_RESET,
    MERGE,
    PUSH,
    RAW_MERGE,
    judge_rows,
    judged_differently,
    refused_wrongly,
)

GATE_REASON = "commit gate"
AMEND_TAIL = "commit --amend --no-edit"


def test_an_amend_is_refused_whichever_global_options_its_git_is_given() -> None:
    assert refused_wrongly(judge_rows(AMEND, wrappers=False)) == {}


def test_a_push_to_the_default_branch_is_refused_whichever_options_git_is_given() -> None:
    assert refused_wrongly(judge_rows(PUSH, wrappers=False)) == {}


def test_a_force_push_to_the_default_branch_is_refused_whichever_options_git_is_given() -> None:
    assert refused_wrongly(judge_rows(FORCE_PUSH, wrappers=False)) == {}


def test_a_merge_is_refused_with_the_repository_given_before_the_subcommand() -> None:
    assert refused_wrongly(judge_rows(MERGE, wrappers=False)) == {}


def test_a_merge_through_the_raw_api_is_refused_with_the_method_either_side_of_the_path() -> None:
    assert refused_wrongly(judge_rows(RAW_MERGE, wrappers=False)) == {}


def test_a_forbidden_command_behind_a_wrapper_or_a_directory_change_is_refused() -> None:
    assert refused_wrongly(judge_rows(AMEND, MERGE, wrappers=True)) == {}


def test_a_hard_reset_and_a_branch_force_delete_are_refused_with_a_directory_option() -> None:
    assert refused_wrongly(judge_rows(HARD_RESET, BRANCH_DELETE)) == {}


def test_reading_through_the_options_that_hide_an_amend_is_allowed() -> None:
    rows = judge_rows(AMEND, wrappers=False)
    for read in ("log", "status", "diff"):
        wrong = judged_differently(
            rows, lambda command, read=read: command.replace(AMEND_TAIL, read), allowed=True
        )
        assert wrong == {}, read


def test_pushing_the_units_own_branch_is_allowed_through_the_same_options() -> None:
    own = probe_branch()
    wrong = judged_differently(
        judge_rows(PUSH, wrappers=False),
        lambda command: (
            command.replace("push origin main", f"push origin {own}")
            if command.endswith("push origin main")
            else None
        ),
        allowed=True,
    )
    assert wrong == {}


def test_a_commit_message_that_mentions_a_forbidden_command_is_allowed() -> None:
    wrong = judged_differently(
        judge_rows(AMEND, wrappers=False),
        lambda command: command.replace(AMEND_TAIL, 'commit -m "never run gh pr merge 1"'),
        allowed=True,
    )
    assert wrong == {}


def test_a_gh_read_is_allowed_with_the_repository_option() -> None:
    wrong = judged_differently(
        judge_rows(MERGE, wrappers=False),
        lambda command: command.replace("pr merge 1", "pr view 1"),
        allowed=True,
    )
    assert wrong == {}


def test_a_gh_api_read_is_allowed_with_the_same_method_options() -> None:
    rows = judge_rows(RAW_MERGE, wrappers=False)
    for path in ("pulls/1/comments", "commits/abc123/check-runs"):
        wrong = judged_differently(
            rows,
            lambda command, path=path: command.replace("pulls/1/merge", path).replace("PUT", "GET"),
            allowed=True,
        )
        assert wrong == {}, path


def test_skipping_the_commit_gate_is_judged_as_before_through_a_global_option() -> None:
    rows = judge_rows(AMEND, wrappers=False)
    wrong = judged_differently(
        rows,
        lambda command: command.replace(AMEND_TAIL, "commit --no-verify -m x"),
        allowed=False,
        reason=GATE_REASON,
    )
    assert wrong == {}


def test_a_hooks_path_set_through_a_global_option_is_judged_as_before() -> None:
    rows = judge_rows(AMEND, wrappers=False)
    wrong = judged_differently(
        rows,
        lambda command: command.replace(AMEND_TAIL, "-c core.hooksPath=/dev/null status"),
        allowed=False,
        reason=GATE_REASON,
    )
    assert wrong == {}
