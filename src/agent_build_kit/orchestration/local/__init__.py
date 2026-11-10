"""The local implementations of the orchestration interfaces."""

from __future__ import annotations

from agent_build_kit import orchestration
from agent_build_kit.orchestration.artifacts import INTERFACE as ARTIFACTS
from agent_build_kit.orchestration.local.artifacts import LocalArtifacts


def register_implementations() -> None:
    """Register the local implementation of each interface for `local` deployments."""
    orchestration.register(ARTIFACTS, "local", LocalArtifacts)
