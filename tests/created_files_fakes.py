"""Toolchain profiles that name the files their commands create, for the tests of what the
pipeline owns in a repository with no environment section.

`Creates` is the python-uv profile with one hook added, so the checks the pipeline runs
through a profile still work; what it names is the test's own, in a neutral shape, and one
profile's files are not another's. `Hookless` is a profile written before the hook existed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig, RepoConfig
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.environment_fakes import FakeEnvironment, repo_config

LOCK = "deps.lock"
NESTED = "frontend/pins.lock"


class Creates(PythonUvProfile):
    """A profile whose commands create `files`."""

    def __init__(self, name: str, *files: str) -> None:
        self.name = name
        self.files = list(files)

    def created_files(self, repo: Path) -> list[str]:
        return list(self.files)


class Hookless(PythonUvProfile):
    """A profile written before the hook: it has none."""

    name = "hookless"
    created_files = None  # type: ignore[assignment]


MAKES_LOCK = Creates("makes-lock", LOCK)
MAKES_NESTED = Creates("makes-nested", NESTED)
MAKES_NOTHING = Creates("makes-nothing")


@contextmanager
def registered(*extra: PythonUvProfile) -> Iterator[None]:
    """The profiles above, and `extra`, registered for a `with` block."""
    with ExitStack() as stack:
        for profile in (MAKES_LOCK, MAKES_NESTED, MAKES_NOTHING, Hookless(), *extra):
            stack.enter_context(profiles.registered(profile))
        yield


def configured(
    root: Path,
    profile: str,
    env: FakeEnvironment | None = None,
    projects: list[ProjectConfig] | None = None,
) -> RepoConfig:
    """The fixture repository `app` using `profile`, with `env` as its environment."""
    return repo_config(root, env).model_copy(
        update={"profile": profile, "projects": projects or []}
    )
