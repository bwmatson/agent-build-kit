"""A refused merge command says the agent never merges and names no one who does."""

import re

import pytest

from agent_build_kit.pipeline.command_policy import check_command

SPEC = "spec/add-marker/1-unit"
COMMANDS = ["gh pr merge 4 --squash", "git status && gh pr merge 4"]


@pytest.mark.parametrize("command", COMMANDS)
def test_the_refusal_says_the_agent_never_merges(command: str) -> None:
    verdict = check_command(command, branch=SPEC)

    assert not verdict.allowed
    assert "the agent never merges" in (verdict.reason or "")


@pytest.mark.parametrize("command", COMMANDS)
def test_the_refusal_names_no_one_who_does(command: str) -> None:
    reason = check_command(command, branch=SPEC).reason or ""

    assert not re.search(r"\b(human|person|people|someone|everyone)\b", reason, re.I)
