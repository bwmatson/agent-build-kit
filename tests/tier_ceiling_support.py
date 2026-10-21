"""What the per-tier ceiling tests share: plans in the raw shape a model sends, over groups
that are not flagged, and a repo that overrides a ceiling."""

from __future__ import annotations

import json
from typing import Any

from agent_build_kit import config as config_module
from agent_build_kit.config import RepoReviewConfig
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import activate_with

GROUPS = [
    TaskGroup(number=n, repo="app", tier="unit-test", title=title, line=3 + 6 * n, task_count=2)
    for n, title in enumerate("ABC", start=1)
]


def configure(*, enabled: bool, repo_ceilings: dict[str, int] | None = None) -> None:
    """The workspace with `review.enabled` set, and `app` overriding these ceilings."""
    updated = activate_with(review={"enabled": enabled})
    if repo_ceilings is not None:
        app = updated.repos["app"].model_copy(
            update={"review": RepoReviewConfig.model_validate({"ceilings": repo_ceilings})}
        )
        config_module.activate(
            updated.model_copy(update={"repos": {**updated.repos, "app": app}}),
            config_module.active_root(),
        )


def graph(*units: dict[str, Any]) -> str:
    body = [
        {"change": "c", "title": "A unit", "repo": "app", "tier": "unit-test", **unit}
        for unit in units
    ]
    return json.dumps({"units": body})
