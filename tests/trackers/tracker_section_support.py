"""Shared by the tracker section tests: raw sections and the call that activates them."""

from __future__ import annotations

from typing import Any

from agent_build_kit import config as config_module

AZURE = {
    "kind": "azure_devops",
    "organization": "example-org",
    "project": "Example Project",
    "team": "Example Team",
    "area_path": "Example Project\\Area",
    "iteration_path": "Example Project\\Iteration 1",
    "story_type": "User Story",
    "token_env": "TRACKER_PAT",
}
LABELS = {"feature": "type:feature", "story": "type:story", "task": "type:task"}
GITHUB = {
    "kind": "github",
    "owner": "example",
    "repo": "app",
    "labels": LABELS,
    "token_env": "TRACKER_TOKEN",
}
# Shaped like a real personal access token, which a section must never hold.
TOKEN_SHAPED = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"

AZURE_BLOCK = {
    "organization": "example-org",
    "project": "Example Project",
    "team": "Example Team",
    "area_path": "Example Project\\Area",
    "iteration_path": "Example Project\\Iteration 1",
    "types": {"epic": "Epic", "change": "Issue", "group": "Task"},
    "states": {"new": "To Do", "active": "Doing", "done": "Done"},
}
# A Basic-process board: an Epic made by hand, an Issue per change and a Task per group.
BASIC = {
    "kind": "azure_devops",
    "token_env": "TRACKER_PAT",
    "levels": ["change", "group"],
    "epic": True,
    "azure_devops": AZURE_BLOCK,
}
GITHUB_BLOCK = {
    "owner": "example",
    "repo": "app",
    "types": {"change": "type:change", "group": "type:group", "task": "type:task"},
}


def configure(**trackers_by_repo: dict[str, Any] | None) -> None:
    """Activate the default workspace with these repos' `tracker` sections set."""
    current = config_module.active()
    repos = {
        name: repo.model_copy(update={"tracker": trackers_by_repo.get(name, repo.tracker)})
        for name, repo in current.repos.items()
    }
    config_module.activate(current.model_copy(update={"repos": repos}), config_module.active_root())
