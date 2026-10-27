"""A planning repository whose `abk.yaml` is committed, and `abk doctor`'s
`public content` findings about it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import yaml

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig, WorkspaceConfig, dump, merge_local
from tests.cli.test_doctor import Answers
from tests.factories import git, init_repo, which_all

CHECK = "public content"
ORIGIN = "https://github.com/example/plan.git"

# `abk doctor`'s `machine keys` check: the overlay file, its two fix texts, and the accounts
# and test dimension a document needs for the keys that name them to load.
OVERLAY = "abk.local.yaml"
WARN_FIX = "move it to abk.local.yaml with `abk config --migrate`"
NOTE_FIX = (
    "fine to commit; move it to abk.local.yaml to differ "
    "(`abk config --migrate --include-defaults` moves it)"
)
ACCOUNTS = {"runtimes": {"claude_code": {"accounts": {"kit": {"max_units_in_progress": 2}}}}}
DECLARED = {"tests": {"e2e_dimensions": {"os": {"linux": {"marker": "linux"}}}}}


def planning(
    root: Path,
    *,
    repos: dict[str, RepoConfig] | None = None,
    verify_env: dict[str, dict] | None = None,
    origin: str | None = ORIGIN,
    tracked: bool = True,
    ignore: str = "",
    repository: bool = True,
    state_dir: str | None = None,
    publish: str | None = None,
) -> Path:
    """A planning root holding `abk.yaml` (tracked, or only written) and a
    `.gitignore`; the path of `abk.yaml`. A repo entry defaults to the checkout."""
    root.mkdir(parents=True, exist_ok=True)
    if repos is None:
        repos = {"app": RepoConfig(path=Path("."), slug="example/app", changelog=None)}
    data = WorkspaceConfig(repos=repos).model_dump(by_alias=True, mode="json")
    chosen = {"state_dir": state_dir or "runs", "publish": publish}
    extra = {"planning": {k: v for k, v in chosen.items() if v}}
    config = WorkspaceConfig.model_validate({**data, **extra, "verify": {"env": verify_env or {}}})
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


def committed_config(
    root: Path,
    committed: dict[str, Any],
    *,
    overlay: dict[str, Any] | None = None,
    tracked: bool = True,
    repository: bool = True,
) -> Path:
    """A planning root whose abk.yaml holds `committed` laid over the declared test dimension
    (committed, untracked, or outside a repository), and `overlay` in the ignored
    abk.local.yaml when given; the path of abk.yaml."""
    config = planning(root, ignore=OVERLAY + "\n", tracked=tracked, repository=repository)
    document = merge_local(merge_local(yaml.safe_load(config.read_text()), DECLARED), committed)
    config.write_text(yaml.safe_dump(document, sort_keys=False))
    if repository and tracked:
        git(root, "commit", "-qam", "machine keys", "--allow-empty")
    if overlay is not None:
        (root / OVERLAY).write_text(yaml.safe_dump(overlay))
    return config
