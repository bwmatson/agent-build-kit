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

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src" / "agent_build_kit"
WORKER_SOURCE = REPOSITORY_ROOT / "packages" / "worker" / "src" / "agent_build_kit"
# The modules the package table assigns to the worker, as paths under a source tree.
WORKER_MODULES = (
    "graph/build.py",
    "graph/check_loop.py",
    "graph/nodes.py",
    "graph/run.py",
    "graph/state.py",
    "graph/unit.py",
    "pipeline/resolution_lane.py",
    "pipeline/verify.py",
    "cli/worker.py",
)


def source_trees() -> list[Path]:
    """Every source tree of the `agent_build_kit` namespace: the root project's and each
    package's under `packages/`. A guard over the framework's source walks these, never
    `SOURCE_ROOT` alone."""
    packages = sorted(REPOSITORY_ROOT.glob("packages/*/src/agent_build_kit"))
    return [SOURCE_ROOT, *(tree for tree in packages if tree.is_dir())]


def source_files(pattern: str = "*.py") -> list[tuple[Path, Path]]:
    """Each file of the source trees matching `pattern` as `(its tree, the file)`, in a stable
    order; the file's name relative to its tree is `path.relative_to(tree)`."""
    return [(tree, path) for tree in source_trees() for path in sorted(tree.rglob(pattern))]


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
    beside: Collection[Path] = (),
) -> list[str]:
    """Problems of the tree under `root` and of each tree of `beside`, files named relative to
    their own tree."""
    pattern = re.compile("|".join(rf"(?<![\w.-]){re.escape(token)}(?![\w-])" for token in tokens))
    problems: list[str] = []
    named: set[str] = set()
    for tree in (root, *beside):
        for path in sorted(tree.rglob("*.py")):
            name = path.relative_to(tree).as_posix()
            problems += _file_problems(path, name, pattern, named, allowlist, own_tooling)
    problems.extend(
        f"{name}: on the allowlist but names no ecosystem; remove it"
        for name in sorted(set(allowlist) - named)
    )
    problems.extend(
        f"{name}: on the own-tooling list but names no ecosystem; remove it"
        for name in sorted(set(own_tooling) - named)
    )
    return problems


def _file_problems(
    path: Path,
    name: str,
    pattern: re.Pattern[str],
    named: set[str],
    allowlist: Collection[str],
    own_tooling: Collection[str],
) -> list[str]:
    if name.split("/")[0] in EXEMPT_FOLDERS:
        return []
    lines = [
        number
        for number, text in enumerate(path.read_text().splitlines(), start=1)
        if pattern.search(text)
    ]
    if not lines:
        return []
    named.add(name)
    if name in allowlist or name in own_tooling:
        return []
    return [f"{name}:{line}: names a package manager or lock file" for line in lines]
