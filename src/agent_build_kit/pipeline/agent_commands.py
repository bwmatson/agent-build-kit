"""The commands a build agent may run, and the section of a prompt that names them.

They come from the repo's toolchain profiles, or from `repos.<name>.agent_commands` when that
replaces them. A command is only worth naming if the tool list the build starts with allows
it, so each is judged by the same matcher the ACP runtime applies."""

from __future__ import annotations

from agent_build_kit import forges, profiles
from agent_build_kit.config import AGENT_PATH_WORD, AgentCommand, AgentScope, RepoConfig
from agent_build_kit.pipeline import wiring
from agent_build_kit.profiles.base import AgentCommands
from agent_build_kit.tool_patterns import allows

# The most a prompt's section may add, in characters.
NOTE_LIMIT = 600

HEADING = "Commands you may run to test, lint and format; any other command will be refused:"

# What the agent picks, as the section shows it, and a word that stands for it when judging.
_SHOWN = {AgentScope.FILE: "<path>", AgentScope.NODE_ID: "<test id>"}
_SCOPE_WORDS = {AgentScope.WHOLE: "whole repo", AgentScope.FILE: "one file"}
_SAMPLE_WORD = "sample"


def _own(profile: object) -> tuple[AgentCommand, ...]:
    return profile.agent_commands if isinstance(profile, AgentCommands) else ()


def effective(repo: RepoConfig) -> list[AgentCommand]:
    """The repo's override, else its profile's commands followed by each project profile's,
    each once, in that order."""
    if repo.agent_commands is not None:
        return list(repo.agent_commands)
    chosen = [profiles.get(repo.profile), *(profiles.get(p.profile) for p in repo.projects)]
    found: dict[tuple[str, tuple[str, ...], str], AgentCommand] = {}
    for profile in chosen:
        for item in _own(profile):
            found.setdefault((item.purpose, tuple(item.command), item.scope), item)
    return list(found.values())


def allow_list(repo: RepoConfig) -> str:
    """The tool list a build is started with for `repo`."""
    return wiring.allowed_tools(profiles.get(repo.profile), forges.get(repo.forge), repo.projects)


def judged_line(item: AgentCommand) -> str:
    return " ".join(item.command).replace(AGENT_PATH_WORD, _SAMPLE_WORD)


def refused(repo: RepoConfig) -> list[tuple[int, str]]:
    """The position and line of each effective command the build's tool list does not allow."""
    tools = allow_list(repo)
    return [
        (index, judged_line(item))
        for index, item in enumerate(effective(repo))
        if not allows(tools, judged_line(item))
    ]


def _line(item: AgentCommand) -> str:
    shown = " ".join(item.command).replace(AGENT_PATH_WORD, _SHOWN.get(item.scope, ""))
    scope = _SCOPE_WORDS.get(item.scope, "one test")
    return f"- {item.purpose}, {scope}: {shown}\n"


def _fitting(commands: list[AgentCommand]) -> list[AgentCommand]:
    """The leading commands whose whole lines fit the bound with the heading."""
    used = len(HEADING) + 2
    fit: list[AgentCommand] = []
    for item in commands:
        used += len(_line(item))
        if used > NOTE_LIMIT:
            break
        fit.append(item)
    return fit


def left_out(repo: RepoConfig) -> list[AgentCommand]:
    """The effective commands the section leaves out for want of room."""
    commands = effective(repo)
    return commands[len(_fitting(commands)) :]


def commands_note(repo: RepoConfig | None) -> str:
    """The section a build prompt carries, or `""` when the repo has no commands or not one
    line fits. A line that does not fit is left out whole, and so are those after it."""
    if repo is None:
        return ""
    fit = _fitting(effective(repo))
    if not fit:
        return ""
    return HEADING + "\n" + "".join(_line(item) for item in fit) + "\n"
