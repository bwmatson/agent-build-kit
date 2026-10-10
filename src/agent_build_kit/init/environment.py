"""What `abk init` writes into an `environment` section.

The one place that guesses: it reads marker files in a checkout and proposes
commands and file lists. Once written they are plain configuration, and
nothing downstream reads these guesses again.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path, PurePosixPath

from agent_build_kit.config import EnvironmentConfig, EnvironmentInputs

MANIFEST = "pyproject.toml"
LOCK = "uv.lock"


def _relative(path: Path, root: Path) -> str:
    return Path(os.path.relpath(path, root)).as_posix()


def _path_sources(root: Path) -> list[Path]:
    """The checkouts the manifest names as path sources, that exist."""
    try:
        data = tomllib.loads((root / MANIFEST).read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return []
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    found = []
    for source in sources.values():
        path = source.get("path") if isinstance(source, dict) else None
        if isinstance(path, str) and (root / path).is_dir():
            found.append((root / path).resolve())
    return found


def detect_environment(root: Path, *, framework: bool) -> EnvironmentConfig | None:
    """The section for the checkout at `root`, or None where nothing is
    recognised. `framework` says the pipeline itself runs from this
    environment, so its check loads the framework."""
    root = root.expanduser().resolve()
    if not (root / MANIFEST).is_file():
        return None
    dependencies, lock = [MANIFEST], []
    if (root / LOCK).is_file():
        lock.append(LOCK)
    for checkout in _path_sources(root):
        for name, files in ((MANIFEST, dependencies), (LOCK, lock)):
            # A pattern cannot leave the repository, so a checkout beside it is not listed.
            if (checkout / name).is_file() and not _relative(checkout / name, root).startswith(
                ".."
            ):
                files.append(_relative(checkout / name, root))
    check = (
        ["uv", "run", "--no-sync", "python", "-c", "import agent_build_kit"]
        if framework
        else ["uv", "run", "--no-sync", "python", "-c", "pass"]
    )
    return EnvironmentConfig(
        sync=["uv", "sync"],
        check=check,
        inputs=EnvironmentInputs(dependencies=dependencies, lock=lock),
    )


def unrecognised() -> EnvironmentConfig:
    """The section written where nothing is recognised: empty commands, which
    configuration refuses until they are set by hand."""
    return EnvironmentConfig.model_construct(sync=[], check=[], inputs=EnvironmentInputs())


def lock_patterns(*environments: EnvironmentConfig | None) -> list[str]:
    """The lock files' names, once each, for the generated-file patterns."""
    names: list[str] = []
    for environment in environments:
        for path in environment.inputs.lock if environment else []:
            name = PurePosixPath(path).name
            if name not in names:
                names.append(name)
    return names
