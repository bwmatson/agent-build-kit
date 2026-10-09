"""What the approve tests share: a host that records what reaches it, a remote that
shows whether anything was pushed, and the review file a unit's decisions are kept in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit import forges
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.installation import Installation
from tests.factories import git, init_repo
from tests.forges.mock_host import MockHost, ok


def watch_the_host() -> MockHost:
    """Replace the registered GitHub forge with one over a host that records its requests."""
    host = MockHost(ok({"message": "Not Found"}, 404))
    forges.register(GitHubForge(http=host))
    return host


def give_a_remote(repo: Path) -> Path:
    """A bare `origin` for `repo`, holding nothing: whatever it holds later was pushed."""
    remote = repo.parent / f"{repo.name}-origin.git"
    remote.mkdir(parents=True)
    git(remote, "init", "-q", "--bare", "-b", "main")
    git(repo, "remote", "add", "origin", str(remote))
    return remote


def refs(remote: Path) -> str:
    return git(remote, "for-each-ref")


def without_a_branch(installation: Installation) -> Path:
    """The `app` checkout with `main` only: a unit's branch is not in it."""
    repo = init_repo(installation.checkouts["app"])
    (repo / "base.txt").write_text("base\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")
    return repo


def _review_file(installation: Installation, unit_id: str) -> Path:
    return installation.state_dir / "reviews" / f"{unit_id.replace('/', '-')}.json"


def stored_decisions(installation: Installation, unit_id: str) -> list[dict[str, Any]]:
    path = _review_file(installation, unit_id)
    if not path.exists():
        return []
    return json.loads(path.read_text())["decisions"]


def write_an_old_decision(installation: Installation, unit_id: str, round_: int) -> None:
    """A decision as it was stored before decisions carried a head."""
    path = _review_file(installation, unit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    old = {
        "round": round_,
        "decision": "request_changes",
        "summary": "Needs a test",
        "at": "2026-01-01T00:00:00+00:00",
    }
    path.write_text(json.dumps({"threads": [], "decisions": [old]}))
