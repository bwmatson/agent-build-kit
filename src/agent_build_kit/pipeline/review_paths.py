"""The paths that never land without a person: the framework's defaults and the installation's."""

from __future__ import annotations

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.path_patterns import matches_any

# Database migrations, CI and deploy configuration, container definitions, secrets and key
# material, and ownership files.
PROTECTED_DEFAULTS: tuple[str, ...] = (
    "**/migrations/**",
    ".github/**",
    ".gitlab-ci.yml",
    ".circleci/**",
    "**/Dockerfile",
    "**/Dockerfile.*",
    "**/docker-compose*.yml",
    "**/docker-compose*.yaml",
    "**/compose*.yml",
    "**/compose*.yaml",
    "**/.env",
    "**/.env.*",
    "**/secrets/**",
    "**/*.pem",
    "**/*.key",
    "**/CODEOWNERS",
)


def protected_globs(config: WorkspaceConfig, repo: str) -> tuple[str, ...]:
    """The globs protecting `repo`: the defaults (unless switched off), the workspace's list
    and the repo's own, which only ever adds."""
    review = config.review
    own = config.repos[repo].review.protected_paths if repo in config.repos else []
    defaults = PROTECTED_DEFAULTS if review.protected_defaults else ()
    return (*defaults, *review.protected_paths, *own)


def is_protected(config: WorkspaceConfig, repo: str, path: str) -> bool:
    """Whether `path` in `repo` is matched by the repo's protected globs."""
    return matches_any(protected_globs(config, repo), path)
