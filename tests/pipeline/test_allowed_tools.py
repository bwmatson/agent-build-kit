"""What an agent may run is composed from the forge of the repo it works in."""

from __future__ import annotations

from agent_build_kit import forges
from agent_build_kit.pipeline.wiring import allowed_tools
from agent_build_kit.profiles.python_uv import PROFILE

# What a GitHub agent was given before the allow-list came from the forge.
GITHUB_BEFORE = (
    "Read Edit Write Grep Glob Bash(git *) Bash(gh pr view*) Bash(gh pr diff*) "
    f"{PROFILE.allowed_tools}"
).strip()


def test_an_azure_agent_can_read_its_pr_and_not_through_gh() -> None:
    tools = allowed_tools(PROFILE, forges.get("azure_devops"))

    assert "Bash(az repos pr show*)" in tools
    assert "gh pr" not in tools


def test_an_azure_agent_is_given_no_way_to_complete_a_pr() -> None:
    tools = allowed_tools(PROFILE, forges.get("azure_devops"))

    for denied in ("az repos pr update", "az repos pr set-vote", "az rest", "az devops invoke"):
        assert denied not in tools


def test_a_github_agent_is_given_exactly_what_it_was() -> None:
    assert allowed_tools(PROFILE, forges.get("github")) == GITHUB_BEFORE


def test_no_forge_reads_with_a_command_any_forge_denies() -> None:
    for forge in map(forges.get, forges.names()):
        assert forge.read_commands, f"{forge.name} declares no way to read a PR"
        for read in forge.read_commands:
            for other in map(forges.get, forges.names()):
                for denied in other.denied_commands:
                    shared = min(len(read), len(denied))
                    assert read[:shared] != denied[:shared], (
                        f"{forge.name} reads with {read}, which {other.name} denies as {denied}"
                    )
