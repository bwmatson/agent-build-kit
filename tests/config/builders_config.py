"""A minimal workspace for the `builders.stubbed_tdd_commits` tests."""

from __future__ import annotations

from typing import Any

from agent_build_kit.config import WorkspaceConfig

REPO = {"app": {"path": "/work/app", "slug": "example/app"}}


def load(builders: Any = None) -> WorkspaceConfig:
    data: dict[str, Any] = {"repos": REPO}
    if builders is not None:
        data["builders"] = builders
    return WorkspaceConfig.model_validate(data)
