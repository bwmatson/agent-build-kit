"""What denies an agent a merge is what it was before the pipeline could land a unit itself.

The landing step merges through a forge's merge operation, never through the agent, so the
policy hook, the command policy, each forge's denied commands and requests and the runtime's
disallowed tools stay as they were, and nothing but the landing step calls the operation.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

import agent_build_kit
from agent_build_kit import forges
from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import DeniedRequest
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.local import LocalForge
from agent_build_kit.hooks.policy import decide
from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.runtimes.claude_code import DISALLOWED, disallowed

MERGES = (
    "gh pr merge 4",
    "gh api -X PUT repos/example/app/pulls/4/merge",
    "az repos pr update --id 4 --status completed",
    "az repos pr set-vote --id 4 --vote 10",
    "az repos policy list",
    "az rest --method patch --url https://dev.azure.com/x",
    "az devops invoke --area git --resource pullRequests",
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", "-b", "spec/change/1"], cwd=tmp_path, check=True)
    return tmp_path


def payload(command: str, cwd: Path) -> dict:
    return {
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


@pytest.mark.parametrize("command", MERGES)
def test_the_policy_hook_denies_every_merge(command: str, repo: Path) -> None:
    answer = decide(payload(command, repo))

    assert answer is not None
    assert answer["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("command", MERGES)
def test_the_command_policy_denies_every_merge(command: str, repo: Path) -> None:
    verdict = check_command(command, branch="spec/change/1", cwd=repo)

    assert not verdict.allowed
    assert "never merges" in verdict.reason


def test_the_github_forge_denies_its_merge_command_and_request() -> None:
    assert GitHubForge.denied_commands == (("gh", "pr", "merge"),)
    assert GitHubForge.denied_requests == (
        DeniedRequest(
            command=("gh", "api"), methods=("PUT", "POST"), path=r"/pulls/\d+/merge/?(?:[?#]|$)"
        ),
    )


def test_the_azure_forge_denies_its_completing_commands_and_the_raw_escapes() -> None:
    assert AzureDevOpsForge.denied_commands == (
        ("az", "repos", "pr", "update"),
        ("az", "repos", "pr", "set-vote"),
        ("az", "repos", "policy"),
        ("az", "rest"),
        ("az", "devops", "invoke"),
    )
    assert AzureDevOpsForge.denied_requests == ()


def test_the_local_forge_denies_nothing() -> None:
    assert LocalForge.denied_commands == ()
    assert LocalForge.denied_requests == ()


def test_the_denied_prefixes_are_the_union_of_the_forges() -> None:
    assert forges.denied_prefixes() == (
        "az devops invoke",
        "az repos policy",
        "az repos pr set-vote",
        "az repos pr update",
        "az rest",
        "gh pr merge",
    )


def test_the_runtime_disallows_every_forge_merge_and_its_own_list() -> None:
    assert DISALLOWED == (
        "Bash(git push --force *) Bash(git reset --hard*) Bash(rm -rf*) Bash(git branch -D*)"
    )
    assert disallowed() == (
        "Bash(az devops invoke*) Bash(az repos policy*) Bash(az repos pr set-vote*) "
        "Bash(az repos pr update*) Bash(az rest*) Bash(gh pr merge*) " + DISALLOWED
    )


def test_nothing_but_the_landing_step_calls_the_merge_operation() -> None:
    source = Path(agent_build_kit.__file__).parent
    call = re.compile(r"\.merge_pr\(")
    callers = {
        path.relative_to(source).as_posix()
        for path in source.rglob("*.py")
        if call.search(path.read_text())
    }

    outside = {name for name in callers if not name.startswith("forges/") and "landing" not in name}
    assert outside == set()
