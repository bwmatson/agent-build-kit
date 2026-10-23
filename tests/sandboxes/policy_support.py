"""The scene the sandbox policy tests build: an installation on disk and a policy from it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.installation import Installation, load_installation
from agent_build_kit.sandboxes.policy import build_policy


class StandInRuntime:
    def __init__(self, write: list[str]) -> None:
        self.write = write

    def sandbox_paths(self) -> dict[str, list[str]]:
        return {"write": self.write}


class StandInProfile:
    """A profile with the optional member."""

    def __init__(self, write: list[str]) -> None:
        self.write = write

    def sandbox_paths(self, repo: Path) -> dict[str, list[str]]:
        return {"write": self.write}


class BareProfile:
    """A profile without it."""


class BareRuntime:
    pass


class Scene:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.root = tmp_path / "plan"
        self.main = tmp_path / "main"
        self.worktree = tmp_path / "wt"

    def repos(
        self,
        sandbox: dict[str, Any] | None = None,
        projects: list | None = None,
        tests: dict[str, Any] | None = None,
    ) -> dict:
        app: dict[str, Any] = {
            "path": str(self.main),
            "slug": "example/app",
            "sandbox": sandbox or {},
            "projects": projects or [],
        }
        if tests is not None:
            app["tests"] = tests
        return {"app": app}

    def installation(
        self,
        sandbox: dict[str, Any] | None = None,
        projects: list | None = None,
        local: dict[str, Any] | None = None,
        tests: dict[str, Any] | None = None,
    ) -> Installation:
        """The installation a real load gives: abk.yaml and abk.local.yaml written to disk."""
        self.root.mkdir(exist_ok=True)
        (self.root / "abk.yaml").write_text(
            yaml.safe_dump({"repos": self.repos(sandbox, projects, tests)})
        )
        overlay = self.root / "abk.local.yaml"
        overlay.unlink(missing_ok=True)
        if local is not None:
            overlay.write_text(yaml.safe_dump(local))
        return load_installation(self.root / "abk.yaml")

    def policy(
        self,
        sandbox: dict[str, Any] | None = None,
        *,
        projects: list | None = None,
        runtime: object = BareRuntime(),
        profile: object = BareProfile(),
        local: dict[str, Any] | None = None,
        tests: dict[str, Any] | None = None,
        **options: Any,
    ):
        installation = self.installation(sandbox, projects, local, tests)
        self.worktree.mkdir(exist_ok=True)
        return build_policy(
            installation, "app", self.worktree, runtime=runtime, profile=profile, **options
        )
