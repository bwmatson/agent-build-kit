"""A repository whose branch adds and changes tier 2 tests, and a runner that answers
each tier 2 command as pytest would, for the tests of what a tier 2 unit runs."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_build_kit.config import ProjectConfig, Tier2UnitScope
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.pipeline.wiring import Tier2Session
from agent_build_kit.profiles.python_uv import PROFILE
from tests.factories import git, init_repo, unit

OLD = "def test_old():\n    assert True\n"
CHANGED = "def test_old():\n    assert 1 == 1\n"
NEW = "def test_new():\n    assert True\n"
PASSED = "=" * 20 + " 2 passed in 0.10s " + "=" * 20 + "\n"
NOTHING = "=" * 20 + " 3 deselected in 0.10s " + "=" * 20 + "\n"
# The command tier 2 runs for a repo with no members, before any narrowing.
WHOLE = PROFILE.tier2_commands(Path("."), marker="local_stack")[0]


def branch(
    tmp_path: Path, changed: dict[str, str], *, base_files: dict[str, str] | None = None
) -> tuple[Path, str]:
    """A repo whose base commit holds `base_files` and whose one further commit writes
    `changed` over it. Returns the repo, left on that commit, and the base's sha."""
    repo = init_repo(tmp_path / "repo")
    (repo / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    for name, text in (base_files or {}).items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base", "--allow-empty")
    base = git(repo, "rev-parse", "HEAD").strip()
    for name, text in changed.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unit", "--allow-empty")
    return repo, base


class Ran:
    """A runner that answers every command with `output` and the exit code `code`, and keeps
    each command with where it ran."""

    def __init__(self, output: str = PASSED, code: int = 0) -> None:
        self.output, self.code = output, code
        self.calls: list[tuple[list[str], Path]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.calls.append((command, Path(str(kwargs["cwd"]))))
        return subprocess.CompletedProcess(command, self.code, self.output, "")

    @property
    def commands(self) -> list[list[str]]:
        return [command for command, _ in self.calls]


def session(
    tmp_path: Path,
    run: Callable[..., subprocess.CompletedProcess],
    *,
    scope: Tier2UnitScope = Tier2UnitScope.OWN,
    log: list[str] | None = None,
    projects: list[ProjectConfig] | None = None,
    dev_stack: str | None = None,
    timeout: float = 5,
    profile: Any = None,
    subject: Unit | None = None,
) -> Tier2Session:
    lines = log if log is not None else []
    return Tier2Session(
        subject or unit(tier="tier2"),
        lock=tmp_path / "t2.lock",
        timeout=timeout,
        run=run,
        sha=lambda cwd: "abc1234",
        log=lines.append,
        scope=scope,
        projects=projects,
        dev_stack=dev_stack,
        profile=profile,
    )
