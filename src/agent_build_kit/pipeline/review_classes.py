"""The class a unit belongs to, from the paths it changed."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.model import TestTier
from agent_build_kit.pipeline.review_paths import glob_matches


def class_of(config: WorkspaceConfig, repo: str, kind: TestTier, paths: Sequence[str]) -> str:
    """The first listed class matching every path, else `<repo>/<unit-test|e2e-test>`.

    An `integration-test` unit behaves as a `unit-test` one, so no class is named for it."""
    if paths:
        for name, globs in config.review.classes.items():
            if all(any(glob_matches(g, p, unparsed=False) for g in globs) for p in paths):
                return name
    effective = TestTier.UNIT_TEST if kind is TestTier.INTEGRATION_TEST else kind
    return f"{repo}/{effective.value}"
