"""A planning repository whose `abk.yaml` is committed, and `abk doctor`'s
`public content` findings about it."""

from __future__ import annotations

from pathlib import Path

import httpx

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump
from tests.cli.test_doctor import Answers
from tests.factories import git, init_repo, which_all

CHECK = "public content"
ORIGIN = "https://github.com/example/plan.git"


def planning(
    root: Path,
    *,
    repos: dict[str, RepoConfig] | None = None,
    verify_env: dict[str, dict] | None = None,
    origin: str | None = ORIGIN,
    tracked: bool = True,
    ignore: str = "",
    repository: bool = True,
) -> Path:
    """A planning root holding `abk.yaml` (tracked, or only written) and a
    `.gitignore`; the path of `abk.yaml`. A repo entry defaults to the checkout."""
    root.mkdir(parents=True, exist_ok=True)
    if repos is None:
        repos = {"app": RepoConfig(path=Path("."), slug="example/app", changelog=None)}
    data = WorkspaceConfig(repos=repos).model_dump(by_alias=True, mode="json")
    config = WorkspaceConfig.model_validate({**data, "verify": {"env": verify_env or {}}})
    (root / "abk.yaml").write_text(dump(config))
    (root / ".gitignore").write_text(ignore)
    if repository:
        init_repo(root)
        if origin:
            git(root, "remote", "add", "origin", origin)
        if tracked:
            git(root, "add", "abk.yaml", ".gitignore")
            git(root, "commit", "-qm", "planning")
    return root / "abk.yaml"


def public_content(config: Path, *, transport: httpx.BaseTransport | None = None) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all, transport=transport)
    return [check for check in checks if check.name == CHECK]


def said(check: Check) -> str:
    return f"{check.detail} {check.fix}"
