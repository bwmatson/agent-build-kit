"""The code hosts a repo can name in abk.yaml."""

from __future__ import annotations

import re
import time
from typing import cast

from agent_build_kit.forges.base import (
    DeniedRequest,
    FileChange,
    Forge,
    Label,
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
    """Make `forge` available by name, behind the one layer that repeats calls."""
    from agent_build_kit.forges.resilient import ResilientForge

    _REGISTRY[forge.name] = forge if isinstance(forge, ResilientForge) else _resilient(forge)


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


def description_limit() -> int:
    """The lowest description limit across the registered forges.

    A description is fitted to this once, where it is handed to a forge, so it
    reads the same on every host and no forge cuts it.
    """
    _load_builtin()
    return min(forge.description_limit for forge in _REGISTRY.values())


def status_limit() -> int:
    """The lowest status description limit across the registered forges.

    A status description is fitted to this once, where it is built, so no forge
    cuts it.
    """
    _load_builtin()
    return min(forge.status_limit for forge in _REGISTRY.values())


def denies(tokens: list[str]) -> str:
    """The reason no agent may run this command, or "" when it may.

    The union over every registered forge, not the current repo's: an agent in
    a GitHub checkout has no business completing an Azure pull request either,
    and a union cannot be weakened by a wrong `forge:` field.
    """
    _load_builtin()
    for forge in _REGISTRY.values():
        for denied in forge.denied_commands:
            if tuple(tokens[: len(denied)]) == denied:
                return f"{' '.join(denied)} is not the agent's to run"
        for request in forge.denied_requests:
            if _sends(tokens, request):
                return (
                    f"{' '.join(request.command)} merging a pull request is not the agent's to run"
                )
    return ""


# Options of a raw API client that carry a request body, which make its default
# method a POST.
BODY_OPTIONS = ("-f", "-F", "--field", "--raw-field", "--input")


def _method_of(args: list[str]) -> str:
    """The method a raw API client sends: the one named (`-X PUT`, `-XPUT`,
    `--method PUT`, `--method=PUT`), else POST when a body is given, else GET."""
    for index, token in enumerate(args):
        if token in ("-X", "--method") and index + 1 < len(args):
            return args[index + 1].upper()
        if token.startswith("--method="):
            return token.split("=", 1)[1].upper()
        if token.startswith("-X") and len(token) > 2:
            return token[2:].removeprefix("=").upper()
    has_body = any(token.split("=", 1)[0] in BODY_OPTIONS for token in args)
    return "POST" if has_body else "GET"


def _sends(tokens: list[str], request: DeniedRequest) -> bool:
    if tuple(tokens[: len(request.command)]) != request.command:
        return False
    args = tokens[len(request.command) :]
    return _method_of(args) in request.methods and any(re.search(request.path, a) for a in args)


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


def read_prefixes() -> tuple[str, ...]:
    """Every registered forge's PR-reading commands, as plain command prefixes.

    What a track, which is not tied to one repo's forge, is allowed to read a
    PR with; a unit's agent gets its own repo's forge's alone.
    """
    _load_builtin()
    return tuple(
        " ".join(command) for forge in _REGISTRY.values() for command in forge.read_commands
    )


# Host-anchored patterns first; the permissive one last (see `identify`).
_ORDER = ("azure_devops", "github")


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from agent_build_kit.forges import azure_devops, github, local

    register(azure_devops.FORGE)
    register(github.FORGE)
    register(local.FORGE)


def _resilient(forge: Forge) -> Forge:
    """`forge` behind the one layer that repeats calls, as the settings say."""
    from agent_build_kit.forges.resilient import ResilientForge, RetryPolicy
    from agent_build_kit.settings import settings

    policy = RetryPolicy(
        attempts=settings.forge_retries + 1, deadline_seconds=settings.forge_deadline_seconds
    )
    return cast(Forge, ResilientForge(forge, policy, time, time.sleep))


__all__ = [
    "FileChange",
    "Forge",
    "Label",
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
    "read_prefixes",
    "register",
]
