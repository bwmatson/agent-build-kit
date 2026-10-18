"""The paths that never land without a person: the framework's defaults and the installation's."""

from __future__ import annotations

from agent_build_kit.config import WorkspaceConfig


def is_protected(config: WorkspaceConfig, repo: str, path: str) -> bool:
    """Whether `path` in `repo` is matched by the repo's protected globs."""
    raise NotImplementedError
