"""Workspaces that carry a `review` section (spec: review-policy)."""

from __future__ import annotations

from typing import Any

from agent_build_kit.config import WorkspaceConfig


def workspace(
    review: dict[str, Any] | None = None, *, app: dict[str, Any] | None = None, platform: Any = None
) -> WorkspaceConfig:
    """A two-repo workspace (`app`, `platform`) whose `review` section is `review` and whose
    repos carry the `review` blocks `app` and `platform` give."""
    repos: dict[str, Any] = {
        "app": {"path": "/work/app", "slug": "example/app"},
        "platform": {"path": "/work/platform", "slug": "example/platform"},
    }
    for name, block in (("app", app), ("platform", platform)):
        if block is not None:
            repos[name]["review"] = block
    document: dict[str, Any] = {"repos": repos}
    if review is not None:
        document["review"] = review
    return WorkspaceConfig.model_validate(document)
