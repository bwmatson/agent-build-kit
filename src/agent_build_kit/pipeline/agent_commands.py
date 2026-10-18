"""The commands a build agent may run, and the section of a prompt that names them."""

from agent_build_kit.config import AgentCommand, RepoConfig


def effective(repo: RepoConfig) -> list[AgentCommand]:
    raise NotImplementedError


def refused(repo: RepoConfig) -> list[tuple[int, str]]:
    raise NotImplementedError


def commands_note(repo: RepoConfig | None) -> str:
    raise NotImplementedError
