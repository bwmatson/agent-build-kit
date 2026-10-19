"""A toolchain profile with its two shell-outs scripted, and the branches the stubbed push
gate's tests judge, for `check_branch` over real git repositories.

The commands are cheap stand-ins for the type checker and the test runner, keyed on files
present at the commit they run at, so a test chooses which tests commit fails which check.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from agent_build_kit.pipeline.check_runner import CheckCache
from agent_build_kit.pipeline.gate import check_branch
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.factories import commit_files as commit
from tests.factories import git, init_repo

TYPE_ERROR = "TYPE_ERROR: return type contradicts the test"
MISSING = "ATTRIBUTE_MISSING: the stub is not there"


class ModeProfile:
    """The Python profile whose clean and red commands fail for named files, recording the
    mode each was asked in.

    `bad_types` is a file whose presence at a tests commit makes the type check fail, and
    `bad_red` one that makes the red run fail with a missing attribute, which only a
    stubbed reading rejects.
    """

    def __init__(self, *, bad_types: str = "", bad_red: str = "") -> None:
        self.bad_types = bad_types
        self.bad_red = bad_red
        self.cleans: list[bool] = []  # `types` of each clean command asked for
        self.reads: list[bool] = []  # `stubbed` of each red reading asked for

    def clean_command(self, *, types: bool = False) -> str:
        self.cleans.append(types)
        if types and self.bad_types:
            return f"if test -f {self.bad_types}; then echo '{TYPE_ERROR}'; exit 1; fi"
        return "exit 0"

    def red_command(self, files: list[str]) -> str:
        shown = f"if test -f {self.bad_red}; then echo '{MISSING}'; fi; " if self.bad_red else ""
        return f"{shown}echo 'FAILED tests'; exit 1"

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False
    ) -> tuple[bool, list[str]]:
        self.reads.append(stubbed)
        if stubbed and MISSING in output:
            return False, ["test_b failed with AttributeError: a stub is missing"]
        return True, []

    def __getattr__(self, name: str) -> Any:
        return getattr(PYTHON, name)


def judged(
    repo: Path, profile: ModeProfile, *, cache: CheckCache | None = None, stubbed: bool = False
) -> list[str]:
    """The push gate over `repo` against `main` with this scripted profile."""
    return check_branch(
        repo, "main", cache=cache, profile=cast(ToolchainProfile, profile), stubbed=stubbed
    )


def repo_on_branch(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    return work


def commit_tests(
    repo: Path, title: str, name: str, content: str = "def test_x(): assert False\n"
) -> str:
    commit(repo, f"test: {title}", {f"tests/test_{name}.py": content})
    return git(repo, "rev-parse", "HEAD")


def commit_feat(repo: Path, title: str, name: str) -> str:
    commit(repo, f"feat: {title}", {f"src/{name}.py": "x = 1\n"})
    return git(repo, "rev-parse", "HEAD")


def two_pairs(repo: Path) -> tuple[str, str]:
    """Two groups, each a tests commit then an implementation commit; the two tests commits."""
    first = commit_tests(repo, "one", "a")
    commit_feat(repo, "one", "a")
    second = commit_tests(repo, "two", "b")
    commit_feat(repo, "two", "b")
    return first, second


def restack_onto_moved_main(repo: Path) -> None:
    """What a merged base does to the branch: every SHA changes, no line does."""
    git(repo, "checkout", "-q", "main")
    commit(repo, "main moves on", {"unrelated.txt": "moved on\n"})
    git(repo, "checkout", "-q", "spec/change/1-unit")
    git(repo, "rebase", "-q", "main")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return repo_on_branch(tmp_path)
