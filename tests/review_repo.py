"""What the review tests share: the `app` checkout of a seeded pipeline given
real branches, so a diff is a real `git diff` between real commits."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from tests.factories import git, init_repo

TWO = "".join(f"two line {n}\n" for n in range(1, 7))


def rev(repo: Path, ref: str) -> str:
    return git(repo, "rev-parse", ref).strip()


def commit(repo: Path, name: str, text: str, message: str) -> str:
    """Write `name` on the checked-out branch, commit it, and return the commit."""
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return rev(repo, "HEAD")


def seed_branches(installation: Installation) -> Path:
    """`main` with a file, `spec/feature/2` adding `two.py`, and `spec/feature/4`
    stacked on it adding `four.py`, with units 2 and 4 in review on them."""
    repo = init_repo(installation.checkouts["app"])
    commit(repo, "base.txt", "base\n", "start")
    git(repo, "checkout", "-q", "-b", "spec/feature/2")
    commit(repo, "two.py", TWO, "two")
    git(repo, "checkout", "-q", "-b", "spec/feature/4")
    commit(repo, "four.py", "four\n", "four")
    git(repo, "checkout", "-q", "main")
    store = UnitStore(installation.state_dir / "units.json")
    store.set_state("feature/4", RUNNING, branch="spec/feature/4")
    store.set_state("feature/4", IN_REVIEW, pr=14)
    return repo


def advance(repo: Path, branch: str, name: str, text: str) -> str:
    """Add a commit to `branch`, leaving `main` checked out."""
    git(repo, "checkout", "-q", branch)
    sha = commit(repo, name, text, f"more {name}")
    git(repo, "checkout", "-q", "main")
    return sha
