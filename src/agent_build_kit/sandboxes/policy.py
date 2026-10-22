"""The policy a confined step runs under, assembled from every place that grants."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.sandboxes.base import SandboxPolicy


class PolicyRefused(ValueError):
    """A grant that would let a step write what a person owns; the message says which and why."""


def build_policy(
    installation: Installation,
    repo: str,
    worktree: Path,
    *,
    runtime: object,
    profile: object,
    local: dict[str, Any] | None = None,
) -> SandboxPolicy:
    """The policy for a step in `worktree` of `repo`: built-ins, then the runtime's and the
    profile's optional `sandbox_paths`, then `repos.<name>.sandbox` and each project's, then
    `local` (the parsed abk.local.yaml)."""
    raise NotImplementedError
