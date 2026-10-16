"""`abk doctor` over a repository that is also the planning root, and its host."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import RepoConfig
from agent_build_kit.init.scaffold import template
from agent_build_kit.pipeline.planning_sync import write_pipeline_marker
from tests.cli.public_content_repo import planning
from tests.cli.test_doctor import Answers
from tests.factories import git, which_all
from tests.forges.stand_in import StandInForge

# What the GitHub forge's `merge_guard` says for a protected branch, one without protection, and
# one whose protection it could not read.
PROTECTED = ""
UNPROTECTED = "no branch protection on main"
UNREADABLE = "cannot tell what guards main: 502 Bad Gateway"

# The packaged `.gitignore`, which holds every line a planning repo ignores.
STATE_IGNORES = template("gitignore")


class Github(StandInForge):
    """The registered `github` forge, answering `merge_guard` as a test chooses."""

    name = "github"


def host_says(guard: str) -> None:
    """Register a `github` forge whose default branch is guarded as `guard` says. The suite
    puts the real one back after each test."""
    forges.register(Github(guard=guard))


def in_repo(
    root: Path, *, publish: str | None = None, ignore: str = STATE_IGNORES, guard: str = PROTECTED
) -> Path:
    """The `abk.yaml` of a repository that lists itself (path `.`) as its one repo."""
    host_says(guard)
    return planning(root, ignore=ignore, publish=publish)


def separate(root: Path, code: Path, *, publish: str | None = None, guard: str = PROTECTED) -> Path:
    """The `abk.yaml` of a planning repository apart from its one code repo, `code`."""
    host_says(guard)
    repos = {"app": RepoConfig(path=code, slug="example/app", changelog=None)}
    return planning(root, repos=repos, ignore=STATE_IGNORES, publish=publish)


def with_pipeline_worktree(config: Path) -> Path:
    """A detached worktree of the repository holding `config`, recorded in its pipeline marker."""
    worktree = config.parent.parent / f"{config.parent.name}-pipeline"
    git(config.parent, "worktree", "add", "-q", "--detach", str(worktree), "HEAD")
    write_pipeline_marker(config.parent, worktree)
    return worktree


def checks_of(config: Path) -> list[Check]:
    return run_doctor(config, run=Answers(), which=which_all)


def named(checks: list[Check], word: str) -> list[Check]:
    """The checks whose name holds `word`."""
    return [check for check in checks if word in check.name]
