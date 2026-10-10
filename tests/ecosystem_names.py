"""The guard against framework code naming an ecosystem.

Framework source other than `profiles/` and `init/` names no package manager, manifest or
lock file from `TOKENS`, as a whole word and not as part of a hyphenated name; comments and
strings count, the text of the file is searched. `check_source` returns one message per
problem: a name in a file that is on neither list is reported as `path:line`; a file on the
allowlist or the own-tooling list with no name left is reported as a stale entry naming it.
"""

from __future__ import annotations

import re
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
    pattern = re.compile("|".join(rf"(?<![\w.-]){re.escape(token)}(?![\w-])" for token in tokens))
    problems: list[str] = []
    named: set[str] = set()
    for path in sorted(root.rglob("*.py")):
        name = path.relative_to(root).as_posix()
        if name.split("/")[0] in EXEMPT_FOLDERS:
            continue
        lines = [
            number
            for number, text in enumerate(path.read_text().splitlines(), start=1)
            if pattern.search(text)
        ]
        if not lines:
            continue
        named.add(name)
        if name in allowlist or name in own_tooling:
            continue
        problems.extend(f"{name}:{line}: names a package manager or lock file" for line in lines)
    problems.extend(
        f"{name}: on the allowlist but names no ecosystem; remove it"
        for name in sorted(set(allowlist) - named)
    )
    problems.extend(
        f"{name}: on the own-tooling list but names no ecosystem; remove it"
        for name in sorted(set(own_tooling) - named)
    )
    return problems
