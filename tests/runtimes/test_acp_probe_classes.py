"""The commands the policy check judges (`PROBE_CLASSES`) stay in step with the command rules:
the list itself, with nothing about driving an agent."""

from __future__ import annotations

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.pipeline.command_spellings import probe_rows
from agent_build_kit.runtimes import acp
from agent_build_kit.runtimes.acp import PROBE_CLASSES, probe_branch

PLAIN_CLASSES = {
    "skipping the commit gate",
    "a hard reset",
    "discarding untracked work",
    "force-deleting a branch",
    "a recursive delete",
    "a bare force push",
}
KEPT = {"PROBE_CLASSES", "probe_branch", "probe_rows"}


def test_every_command_is_one_the_rules_forbid_whichever_branch_or_worktree() -> None:
    for command, label in PROBE_CLASSES:
        for branch in (probe_branch(), "main", "feature"):
            assert not check_command(command, branch=branch).allowed, (label, command, branch)


def test_every_spelling_of_the_table_is_present_and_each_class_has_a_plain_command() -> None:
    commands = [command for command, _label in PROBE_CLASSES]
    assert len(set(commands)) == len(commands), "a command is listed twice"
    assert {spelling.command for _label, spelling in probe_rows()} <= set(commands)
    assert PLAIN_CLASSES <= {label for _command, label in PROBE_CLASSES}


def test_the_list_is_all_that_is_left_of_the_probe() -> None:
    assert [name for name in dir(acp) if "probe" in name.lower() and name not in KEPT] == []
