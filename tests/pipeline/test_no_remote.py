"""A repo with no remote is built against its own trunk and local branches (spec: local-forge).

The repositories are real. A repo with a remote is checked beside the one without, so what is
unchanged is pinned by the same test that pins what is new.
"""

from __future__ import annotations

import subprocess
from contextlib import nullcontext
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.restack import push_with_lease, remote_head
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import branch_name, local_ref
from agent_build_kit.pipeline.wiring import build_fetch, build_push, dev_stack_underneath
from tests.conftest import make_installation
from tests.factories import git, init_repo
from tests.factories import unit as make_unit

UNIT = make_unit("feature/2", repo="app")
BRANCH = branch_name(UNIT)


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(f"{name}\n")
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


def local_repo(path: Path) -> Path:
    """On `main`, no remote, a unit branch one commit ahead, `main` checked out."""
    init_repo(path)
    commit(path, "base.txt")
    git(path, "checkout", "-q", "-b", BRANCH)
    commit(path, "a.txt")
    git(path, "checkout", "-q", "main")
    return path


def remote_repo(path: Path) -> Path:
    """The same, with a bare `origin` that holds `main`."""
    repo = local_repo(path / "clone")
    origin = path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-q", "origin", "main")
    return repo


def test_a_push_without_a_remote_leaves_the_branch_where_it_is(tmp_path: Path) -> None:
    repo = local_repo(tmp_path / "app")
    tip = git(repo, "rev-parse", BRANCH)

    assert push_with_lease(repo, BRANCH, last_pushed=None) == tip

    git(repo, "checkout", "-q", BRANCH)
    newer = commit(repo, "b.txt")
    assert push_with_lease(repo, BRANCH, last_pushed=tip) == newer

    # with a remote the branch is published there, as before
    with_remote = remote_repo(tmp_path / "with")
    sha = push_with_lease(with_remote, BRANCH, last_pushed=None)
    assert git(tmp_path / "with" / "origin.git", "rev-parse", BRANCH) == sha


def test_the_branch_is_read_where_it_is_kept(tmp_path: Path) -> None:
    repo = local_repo(tmp_path / "app")

    assert remote_head(repo, BRANCH) == git(repo, "rev-parse", BRANCH)
    assert remote_head(repo, "spec/missing/1") == ""

    # a remote is still the one asked
    with_remote = remote_repo(tmp_path / "with")
    assert remote_head(with_remote, BRANCH) == ""
    push_with_lease(with_remote, BRANCH, last_pushed=None)
    assert remote_head(with_remote, BRANCH) == git(with_remote, "rev-parse", BRANCH)


def test_the_unit_push_records_the_branch_tip_without_a_remote(tmp_path: Path) -> None:
    repo = local_repo(tmp_path / "app")
    store = UnitStore(tmp_path / "units.json")
    store.upsert([UNIT])

    sha = build_push(store)(BRANCH, cwd=repo)

    assert sha == git(repo, "rev-parse", BRANCH)
    assert store.get(UNIT.id).pushed == sha


def test_the_per_unit_fetch_needs_no_remote_and_still_fetches_from_one(tmp_path: Path) -> None:
    without = local_repo(tmp_path / "without")
    with_remote = remote_repo(tmp_path / "with")
    # `main` moves on the remote after the clone last saw it.
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(tmp_path / "with" / "origin.git"), str(other))
    git(other, "config", "user.email", "t@t.t")
    git(other, "config", "user.name", "t")
    moved = commit(other, "trunk.txt")
    git(other, "push", "-q", "origin", "main")
    fetch = build_fetch({"app": without, "platform": with_remote}, turn=lambda repo: nullcontext())

    fetch(make_unit("feature/2", repo="app"))
    fetch(make_unit("feature/3", repo="platform"))

    assert git(with_remote, "rev-parse", "origin/main") == moved
    assert git(without, "remote") == ""


def test_the_per_pass_fetch_says_nothing_of_a_repo_with_no_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = make_installation(
        tmp_path / "planning",
        repos={
            "app": {"path": str(local_repo(tmp_path / "app")), "forge": "local"},
            "platform": {
                "path": str(remote_repo(tmp_path / "remote")),
                "slug": "example/platform",
            },
        },
    )
    said: list[str] = []
    monkeypatch.setattr(cli, "log", lambda message, **kwargs: said.append(message))

    cli.fetch_all(installation)

    assert said == []


def test_the_base_to_build_on_is_the_local_trunk_without_a_remote(tmp_path: Path) -> None:
    make_installation(
        tmp_path / "planning",
        repos={
            "app": {"path": str(local_repo(tmp_path / "app")), "forge": "local"},
            "platform": {
                "path": str(remote_repo(tmp_path / "remote")),
                "slug": "example/platform",
            },
        },
    )

    assert local_ref("main", repo="app") == "main"
    assert local_ref("main", repo="platform") == "origin/main"
    # a unit's own branch is local either way
    assert local_ref(BRANCH, repo="app") == BRANCH
    assert local_ref(BRANCH, repo="platform") == BRANCH


def test_the_dev_stack_comes_up_from_the_local_trunk_without_a_remote(tmp_path: Path) -> None:
    installation = make_installation(
        tmp_path / "planning",
        planning={"worktree_root": str(tmp_path / "trees")},
        repos={
            "platform": {
                "path": str(local_repo(tmp_path / "platform")),
                "forge": "local",
                "dev_stack": {"script": "scripts/dev-stack.sh"},
            },
            "app": {
                "path": str(local_repo(tmp_path / "app")),
                "forge": "local",
                "consumes": ["platform"],
                "dev_stack": {"script": "scripts/dev-stack.sh"},
            },
        },
    )
    prepared: list[str] = []

    def prepare(repo: Path, name: str, *, ref: str, root: Path) -> Path:
        prepared.append(ref)
        return root / name

    under = dev_stack_underneath(make_unit("feature/2", repo="app"), installation, prepare=prepare)
    assert under is not None
    under()

    assert prepared == ["main"]


def drive_push(tmp_path: Path, repo: Path, store: UnitStore) -> dict:
    """The graph's push step over a real repo with no remote: the real gate and the real push."""
    from agent_build_kit.graph.nodes import BuildPath
    from agent_build_kit.graph.state import UnitRun
    from tests.runner_fakes import Recorder, make_runner

    runner = make_runner(
        store,
        Recorder(store),
        tmp_path,
        worktree=lambda u, base: repo,
        head=lambda cwd: git(cwd, "rev-parse", "HEAD"),
        push=build_push(store),
    )
    path = BuildPath(runner, UNIT, base="main", graph=[], run_log=None, tracer=None)
    return path.push(UnitRun(unit_id=UNIT.id, change=UNIT.change))


def test_the_push_gate_still_requires_the_approved_commit_without_a_remote(tmp_path: Path) -> None:
    repo = local_repo(tmp_path / "app")
    git(repo, "checkout", "-q", BRANCH)
    approved = git(repo, "rev-parse", "HEAD")
    commit(repo, "unreviewed.txt")
    store = UnitStore(tmp_path / "units.json")
    store.upsert([UNIT])
    store.record_approval(UNIT.id, approved)

    outcome = drive_push(tmp_path, repo, store)

    assert "refusing to push" in outcome["stopped"]
    assert store.get(UNIT.id).pushed is None

    # with the head the approved commit, the branch tip is recorded
    store.record_approval(UNIT.id, git(repo, "rev-parse", "HEAD"))

    assert drive_push(tmp_path, repo, store) == {}
    assert store.get(UNIT.id).pushed == git(repo, "rev-parse", BRANCH)
