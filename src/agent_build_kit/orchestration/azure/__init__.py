"""The Azure implementations of the orchestration interfaces."""

from __future__ import annotations

from agent_build_kit import orchestration
from agent_build_kit.orchestration.artifacts import INTERFACE as ARTIFACTS
from agent_build_kit.orchestration.azure.artifacts import build_artifacts


def register_implementations() -> None:
    """Register the Azure implementation of each interface for `azure` deployments."""
    orchestration.register(ARTIFACTS, "azure", build_artifacts)
