"""The hosts that are part of the stack, which a replay never stands in front of."""

from __future__ import annotations

from collections.abc import Mapping

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.model import Frozen
from agent_build_kit.settings import Settings


class InStackHosts(Frozen):
    named: dict[str, str] = {}

    def why(self, host: str) -> str | None:
        """The key that puts `host` in the set (such as `verify.env.NAME`), or None."""
        raise NotImplementedError


def in_stack_hosts(
    workspace: WorkspaceConfig, verify_env: Mapping[str, str], machine: Settings
) -> InStackHosts:
    """The set built from `verify.env` URL values, each repository's code host, the
    machine settings naming stack endpoints, and the always-in-stack names."""
    raise NotImplementedError
