"""The paths that never land without a person: the framework's defaults and the installation's."""

from __future__ import annotations

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.path_patterns import matches

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


def glob_matches(glob: str, path: str, *, unparsed: bool) -> bool:
    """Whether `glob` matches `path`; `unparsed` is the answer for a glob that does not parse,
    which `abk doctor` reports and a decision must not raise on."""
    try:
        return matches(glob, path)
    except ValueError:
        return unparsed


def is_protected(config: WorkspaceConfig, repo: str, path: str) -> bool:
    """Whether `path` in `repo` is matched by the repo's protected globs. A glob that does not
    parse protects: the safe answer when the policy cannot be read."""
    return any(glob_matches(g, path, unparsed=True) for g in protected_globs(config, repo))
