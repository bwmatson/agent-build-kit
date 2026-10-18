"""The class a unit belongs to, from the paths it changed."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.model import TestTier


def class_of(config: WorkspaceConfig, repo: str, kind: TestTier, paths: Sequence[str]) -> str:
    """The first listed class matching every path, else `<repo>/<unit-test|e2e-test>`."""
    raise NotImplementedError
