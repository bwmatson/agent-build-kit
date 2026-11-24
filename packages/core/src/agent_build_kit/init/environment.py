"""What `abk init` writes into an `environment` section.

The toolchain profiles guess: each reads marker files in a checkout and
proposes commands and file lists. Once written they are plain configuration,
and nothing downstream reads these guesses again. This module holds what is
not ecosystem knowledge: the walk, the draft for an unrecognised checkout and
the lock names.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from agent_build_kit import profiles
from agent_build_kit.config import EnvironmentConfig, EnvironmentInputs


def detect_environment(
    root: Path, *, framework: bool, profile: str | None = None
) -> EnvironmentConfig | None:
    """The section for the checkout at `root`, or None where nothing is
    recognised. `framework` says the pipeline itself runs from this
    environment, so its check loads the framework. `profile` names the
    toolchain profile repository detection chose, which is asked first."""
    return profiles.detect_environment(
        root.expanduser().resolve(), framework=framework, first=profile
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
