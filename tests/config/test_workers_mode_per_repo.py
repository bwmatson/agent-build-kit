"""`repos.<name>.workers.mode` overrides the top-level `workers.mode` for that repo's units only
(spec: worker-kinds)."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.config import WorkspaceConfig, workers_mode


def load(top: str | None, app: str | None, platform: str | None = None) -> WorkspaceConfig:
    def repo(name: str, mode: str | None) -> dict[str, Any]:
        entry: dict[str, Any] = {"path": f"/work/{name}", "slug": f"example/{name}"}
        if mode is not None:
            entry["workers"] = {"mode": mode}
        return entry

    document: dict[str, Any] = {
        "repos": {"app": repo("app", app), "platform": repo("platform", platform)}
    }
    if top is not None:
        document["workers"] = {"mode": top}
    return WorkspaceConfig.model_validate(document)


@pytest.mark.parametrize(
    ("top", "app", "platform", "expected"),
    [
        ("threads", "processes", None, {"app": "processes", "platform": "threads"}),
        ("processes", "threads", None, {"app": "threads", "platform": "processes"}),
        ("threads", "processes", "threads", {"app": "processes", "platform": "threads"}),
        ("threads", None, None, {"app": "threads", "platform": "threads"}),
        ("processes", None, None, {"app": "processes", "platform": "processes"}),
        (None, None, None, {"app": "threads", "platform": "threads"}),
        (None, "processes", None, {"app": "processes", "platform": "threads"}),
    ],
)
def test_a_repos_own_mode_wins_and_the_top_level_value_covers_the_rest(
    top: str | None, app: str | None, platform: str | None, expected: dict[str, str]
) -> None:
    config = load(top, app, platform)

    assert {name: workers_mode(repo, config) for name, repo in config.repos.items()} == expected


def test_a_repo_that_is_not_configured_has_the_top_level_mode() -> None:
    config = load("processes", "threads")

    assert workers_mode(None, config) == "processes"
