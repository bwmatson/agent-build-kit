"""The guard against framework code naming an ecosystem.

Framework source other than `profiles/` and `init/` names no package manager, manifest or
lock file from `TOKENS`, as a whole word and not as part of a hyphenated name; comments and
strings count, the text of the file is searched. `check_source` returns one message per
problem: a name in a file that is on neither list is reported as `path:line`; a file on the
allowlist or the own-tooling list with no name left is reported as a stale entry naming it.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "agent_build_kit"

# The one place the names live: a new ecosystem's manager is one line.
TOKENS: tuple[str, ...] = (
    "uv",
    "pip",
    "poetry",
    "npm",
    "npx",
    "pnpm",
    "yarn",
    "cargo",
    "uv.lock",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Cargo.lock",
    "requirements.txt",
)

# Folders that may name an ecosystem: the toolchain profiles and the init detectors.
EXEMPT_FOLDERS: tuple[str, ...] = ("profiles", "init")

# Files that name an ecosystem today and should not. It may only shrink: a file leaves it
# when its names are removed, and nothing is added.
ALLOWLIST: Mapping[str, str] = {
    "cli/doctor.py": "checks `uv run` hook entries against pyproject dependency groups; "
    "belongs behind a profile hook for repository health checks",
    "tracks/runner.py": "the tracks' tool allowlist names `uv run`; belongs to the "
    "profile's allowed tools",
}

# The framework's own tooling, fixed: the framework is itself started, built and shipped
# with tools, and calls the OpenSpec CLI through one.
OWN_TOOLING: Mapping[str, str] = {
    "openspec.py": "the OpenSpec CLI is run through npx",
    "serve/server.py": "the web UI is built with npm",
    "settings.py": "comments on the OpenSpec CLI pin run through npx",
    "config.py": "the openspec.command comment names npx",
    "timers.py": "uv starts a tick, so its availability is checked",
}


def check_source(
    root: Path,
    *,
    allowlist: Collection[str],
    own_tooling: Collection[str],
    tokens: tuple[str, ...] = TOKENS,
) -> list[str]:
    raise NotImplementedError
