"""The commands the policy check judges (`PROBE_CLASSES`) stay in step with the command rules and
the table of spellings: the one home of what is asserted about the list itself."""

from __future__ import annotations

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.pipeline.command_spellings import probe_rows
from agent_build_kit.runtimes.acp import PROBE_CLASSES, probe_branch
from agent_build_kit.runtimes.recommended_policy import UNCOVERED


def test_every_command_is_one_the_rules_forbid_whichever_branch_or_worktree() -> None:
    for command, label in PROBE_CLASSES:
        for branch in (probe_branch(), "main", "feature"):
            assert not check_command(command, branch=branch).allowed, (label, command, branch)


def test_the_list_holds_the_table_s_rows_and_a_plain_command_for_each_other_class() -> None:
    sent = dict(PROBE_CLASSES)
    expected = {spelling.command: label for label, spelling in probe_rows()}
    assert expected
    assert {command: sent.get(command) for command in expected} == expected
    assert len(sent) == len(PROBE_CLASSES), "a command is listed twice"
    plain = {label for command, label in PROBE_CLASSES if command not in expected}
    assert plain == {uncovered.label for uncovered in UNCOVERED}
