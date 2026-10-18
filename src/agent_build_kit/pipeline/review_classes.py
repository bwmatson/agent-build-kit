"""The class a unit belongs to, from the paths it changed."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.model import TestTier
from agent_build_kit.path_patterns import matches_any


def class_of(config: WorkspaceConfig, repo: str, kind: TestTier, paths: Sequence[str]) -> str:
    """The first listed class matching every path, else `<repo>/<unit-test|e2e-test>`.

    An `integration-test` unit behaves as a `unit-test` one, so no class is named for it."""
    if paths:
        for name, globs in config.review.classes.items():
            if all(matches_any(globs, path) for path in paths):
                return name
    effective = TestTier.UNIT_TEST if kind is TestTier.INTEGRATION_TEST else kind
    return f"{repo}/{effective.value}"
