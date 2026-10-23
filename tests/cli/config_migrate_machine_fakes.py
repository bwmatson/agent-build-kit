"""What the tests of `abk config --migrate` moving machine settings share: a git repository that
tracks an abk.yaml holding machine settings, and the merged configuration of its two files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_build_kit.config import merge_local
from tests.factories import git, init_repo
from tests.test_machine_settings import TILDE

MACHINE = (
    "version: 1\n"
    "repos:\n"
    "  app:\n"
    "    slug: example/app\n"
    "    profile: python-uv\n"
    "    path: ../app\n"
    "    deploy:\n"
    f"      ssh_key: {TILDE}.ssh/deploy\n"
    "planning:\n"
    f"  worktree_root: {TILDE}work/trees\n"
    "project_limits:\n"
    "  max_concurrent_stacks: 2\n"
    "verify:\n"
    "  env:\n"
    "    TOKEN:\n"
    "      from: env-file\n"
    f"      file: {TILDE}.config/app/.env\n"
    "      key: TOKEN\n"
)
DEFAULTS = (
    "version: 1\n"
    "repos:\n"
    "  app:\n"
    "    slug: example/app\n"
    "    profile: python-uv\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    limits:\n"
    "      max_units_in_progress: 3\n"
    "tests:\n"
    "  e2e_schedule: off\n"
)
CONFLICT = (
    "left repos.app.path in abk.yaml: abk.local.yaml already sets repos.app.path; keep one of them"
)


def tracked(root: Path, text: str = MACHINE, *, local: str | None = None) -> Path:
    """A repository at `root` with `text` committed as its abk.yaml (and an abk.local.yaml
    written beside it, untracked, when `local` is given); the path of abk.yaml."""
    init_repo(root)
    path = root / "abk.yaml"
    path.write_text(text)
    git(root, "add", "abk.yaml")
    git(root, "commit", "-q", "-m", "start")
    if local is not None:
        (root / "abk.local.yaml").write_text(local)
    return path


def merged(base: str, local: str | None) -> dict[str, Any]:
    """The configuration the two texts make together."""
    return merge_local(yaml.safe_load(base) or {}, yaml.safe_load(local or "") or {})


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def staged(root: Path) -> str:
    return git(root, "diff", "--cached", "--name-only")
