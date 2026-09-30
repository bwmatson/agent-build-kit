"""The code hosts a repo can name in abk.yaml."""

from __future__ import annotations

from agent_build_kit.forges.base import (
    Forge,
    PermittedCommand,
    PullRequest,
    RegistersStacks,
    RepoId,
    ReviewNote,
    Stack,
    StackRefused,
    key,
)

_REGISTRY: dict[str, Forge] = {}


def register(forge: Forge) -> None:
    _REGISTRY[forge.name] = forge


def get(name: str) -> Forge:
    _load_builtin()
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown forge {name!r} (known: {', '.join(names())})") from None


def names() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


def identify(url: str) -> RepoId | None:
    """The repo a remote URL names, or None when no forge recognises it.

    Order matters and is the reason this is not a comprehension over `names()`:
    GitHub's pattern accepts any `alias:owner/name`, an ssh host alias carrying
    a deploy key, so it has to be asked last or it would claim every host's
    ssh remote.
    """
    _load_builtin()
    for name in _ORDER:
        forge = _REGISTRY.get(name)
        if forge and (repo := forge.parse_remote(url)):
            return repo
    return None


def for_repo(name: str) -> tuple[Forge, RepoId]:
    """The forge and identity of a repo in the active workspace.

    The pipeline's equivalent of `shell.repo_slug`: the unit names its repo,
    abk.yaml says where that repo lives. `Installation.forge_of` is the same
    answer for the CLI, which holds an installation rather than the active
    workspace.
    """
    from agent_build_kit.config import active

    repo = active().repos[name]
    forge = get(repo.forge)
    return forge, forge.identity(repo)


def denies(tokens: list[str]) -> str:
    """The reason no agent may run this command, or "" when it may.

    The union over every registered forge, not the current repo's: an agent in
    a GitHub checkout has no business completing an Azure pull request either,
    and a union cannot be weakened by a wrong `forge:` field. A command under a
    denied prefix is allowed only when it matches a forge's `permitted_commands`
    entry completely.
    """
    _load_builtin()
    permitted = [command for forge in _REGISTRY.values() for command in forge.permitted_commands]
    for forge in _REGISTRY.values():
        for denied in forge.denied_commands:
            if tuple(tokens[: len(denied)]) == denied:
                if any(command.matches(tokens) for command in permitted):
                    continue
                return f"{' '.join(denied)} is not the agent's to run"
    return ""


def denied_prefixes() -> tuple[str, ...]:
    """Every registered forge's denied commands, as plain command prefixes.

    The same union `denies` enforces, for the second layer: a runtime renders
    these in its own syntax and refuses them before the agent is offered them,
    so two independent things have to fail before a PR can be merged.
    """
    _load_builtin()
    return tuple(
        sorted(
            " ".join(command) for forge in _REGISTRY.values() for command in forge.denied_commands
        )
    )


# Host-anchored patterns first; the permissive one last (see `identify`).
_ORDER = ("azure_devops", "github")


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.forges import azure_devops, github

    register(azure_devops.FORGE)
    register(github.FORGE)


__all__ = [
    "Forge",
    "PermittedCommand",
    "PullRequest",
    "RegistersStacks",
    "RepoId",
    "ReviewNote",
    "Stack",
    "StackRefused",
    "denied_prefixes",
    "denies",
    "for_repo",
    "get",
    "identify",
    "key",
    "names",
    "register",
]
