"""A restack conflict already resolved once is replayed, not re-derived.

Two units in the same stack often hit the same conflict: a predecessor's merge
produces one hunk, and every sibling built on the same spot conflicts with it
identically. `git rerere` keeps its recordings in `rr-cache` under the
repository's *common* git directory, which every worktree of that repository
shares without anything being copied — so a resolution recorded restacking
one unit is there to replay restacking the next.

What must stay true:

- **The replay is read from the shared cache, not copied between worktrees.**
  Two separate `git worktree add` checkouts of one repo prove that.
- **A replayed resolution is never auto-staged.** It lands in the file, but
  the path stays unmerged until the resolver — now told which paths arrived
  pre-filled — stages it deliberately.
- **An override is recorded in the replayed resolution's place**, so a bad
  cache entry is corrected rather than repeated forever.
- **None of this touches the repository's own git configuration**, and the
  no-resolver path the port/adapt step relies on aborts exactly as it always
  has.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack import (
    ConflictContext,
    RestackConflict,
    _conflicted_files,
    move_branch_onto,
)
from tests.factories import git, init_repo


def commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"write {name}")


def context() -> ConflictContext:
    return ConflictContext(
        moving_unit="add-marker/2",
        moving_intent="register the local value",
        onto_unit="add-marker/1",
        onto_intent="register the predecessor's value",
    )


def rebase_in_progress(tree: Path) -> bool:
    rel = git(tree, "rev-parse", "--git-path", "rebase-merge")
    return (tree / rel).exists()


@pytest.fixture
def landed(tmp_path: Path) -> tuple[Path, str]:
    """main has conflicted.py rewritten by a predecessor unit that already
    merged; `pre` is where every sibling below forked from, before that."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "conflicted.py", "value = 1\n")
    pre = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "spec/c/1")
    commit(repo, "conflicted.py", "value = 2  # predecessor\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge predecessor", "spec/c/1")
    return repo, pre


def sibling(repo: Path, name: str, pre: str) -> None:
    """A unit forked from `pre`, making the identical edit every sibling
    makes — so restacking any of them onto main hits the same hunk."""
    git(repo, "checkout", "-q", "-b", name, pre)
    commit(repo, "conflicted.py", "value = 1  # sibling\n")
    git(repo, "checkout", "-q", "main")


def sibling_worktree(repo: Path, name: str, tmp_path: Path) -> Path:
    """A separate `git worktree add` checkout for `name`, sharing `repo`'s
    common git directory and therefore its rerere cache."""
    tree = tmp_path / "trees" / name.replace("/", "_")
    tree.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-q", str(tree), name)
    return tree


def test_a_resolution_recorded_in_one_worktree_is_replayed_in_a_sibling(
    landed: tuple[Path, str], tmp_path: Path
) -> None:
    repo, pre = landed
    sibling(repo, "spec/c/2", pre)
    sibling(repo, "spec/c/3", pre)
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)
    tree3 = sibling_worktree(repo, "spec/c/3", tmp_path)

    def derives(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree2, "spec/c/2", new_base="main", old_base=pre, resolve=derives, context=context()
    )

    seen: dict = {}

    def confirms(prompt: str, *, cwd: Path) -> None:
        # A real resolver would derive this from scratch; leaving it
        # untouched only works if the replay already put it there.
        seen["content_on_arrival"] = (cwd / "conflicted.py").read_text()

    move_branch_onto(
        tree3, "spec/c/3", new_base="main", old_base=pre, resolve=confirms, context=context()
    )

    assert seen["content_on_arrival"] == "value = 2  # sibling\n"
    git(tree3, "checkout", "-q", "spec/c/3")
    assert (tree3 / "conflicted.py").read_text() == "value = 2  # sibling\n"
    assert not rebase_in_progress(tree3)


def test_the_resolver_is_told_which_paths_carry_a_replayed_resolution(
    landed: tuple[Path, str], tmp_path: Path
) -> None:
    repo, pre = landed
    sibling(repo, "spec/c/2", pre)
    sibling(repo, "spec/c/3", pre)
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)
    tree3 = sibling_worktree(repo, "spec/c/3", tmp_path)

    def derives(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree2, "spec/c/2", new_base="main", old_base=pre, resolve=derives, context=context()
    )

    seen: dict = {}

    def confirms(prompt: str, *, cwd: Path) -> None:
        seen["prompt"] = prompt
        # Still unmerged and unstaged when the resolver is handed it — a
        # replayed resolution is a proposal, not something already accepted.
        seen["conflicted_at_arrival"] = _conflicted_files(cwd)

    move_branch_onto(
        tree3, "spec/c/3", new_base="main", old_base=pre, resolve=confirms, context=context()
    )

    assert "conflicted.py" in seen["conflicted_at_arrival"]
    assert "conflicted.py" in seen["prompt"]
    assert "replayed" in seen["prompt"].lower()


def test_an_override_of_a_replayed_resolution_is_recorded_in_its_place(
    landed: tuple[Path, str], tmp_path: Path
) -> None:
    repo, pre = landed
    sibling(repo, "spec/c/2", pre)
    sibling(repo, "spec/c/3", pre)
    sibling(repo, "spec/c/4", pre)
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)
    tree3 = sibling_worktree(repo, "spec/c/3", tmp_path)
    tree4 = sibling_worktree(repo, "spec/c/4", tmp_path)

    def first_resolution(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree2,
        "spec/c/2",
        new_base="main",
        old_base=pre,
        resolve=first_resolution,
        context=context(),
    )

    def overrides(prompt: str, *, cwd: Path) -> None:
        # Judges the replayed resolution wrong and resolves it differently.
        (cwd / "conflicted.py").write_text("value = 99  # sibling-fixed\n")

    move_branch_onto(
        tree3, "spec/c/3", new_base="main", old_base=pre, resolve=overrides, context=context()
    )

    seen: dict = {}

    def confirms(prompt: str, *, cwd: Path) -> None:
        seen["content"] = (cwd / "conflicted.py").read_text()

    move_branch_onto(
        tree4, "spec/c/4", new_base="main", old_base=pre, resolve=confirms, context=context()
    )

    assert seen["content"] == "value = 99  # sibling-fixed\n", (
        "the override should have replaced what was cached, not the original resolution"
    )


def test_the_rerere_setting_never_touches_the_repositorys_own_configuration(
    landed: tuple[Path, str], tmp_path: Path
) -> None:
    repo, pre = landed
    sibling(repo, "spec/c/2", pre)
    sibling(repo, "spec/c/3", pre)
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)
    tree3 = sibling_worktree(repo, "spec/c/3", tmp_path)

    def derives(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree2, "spec/c/2", new_base="main", old_base=pre, resolve=derives, context=context()
    )

    # The setting rode along on the pipeline's own invocations — it was never
    # written into anything an operator's own git would read.
    local = subprocess.run(
        ["git", "config", "--get", "rerere.enabled"], cwd=repo, capture_output=True, text=True
    )
    assert local.returncode != 0, "the repository's stored configuration must stay untouched"

    global_ = subprocess.run(
        ["git", "config", "--global", "--get", "rerere.enabled"], capture_output=True, text=True
    )
    assert global_.returncode != 0, "nothing here should touch global git configuration either"

    # ...yet the cache it produced is still there to replay from, proving the
    # setting was applied some other way.
    seen: dict = {}

    def confirms(prompt: str, *, cwd: Path) -> None:
        seen["content"] = (cwd / "conflicted.py").read_text()

    move_branch_onto(
        tree3, "spec/c/3", new_base="main", old_base=pre, resolve=confirms, context=context()
    )

    assert seen["content"] == "value = 2  # sibling\n"


def test_without_a_resolver_the_port_step_sees_the_same_abort_as_today(
    landed: tuple[Path, str], tmp_path: Path
) -> None:
    """A cached resolution changes what the resolver has to do, not whether a
    restack with nobody to confirm it still stops. The adapt/port step reads
    exactly this signal — a `RestackConflict` and a clean worktree — and must
    keep seeing it whether or not a replay was available."""
    repo, pre = landed
    sibling(repo, "spec/c/2", pre)
    sibling(repo, "spec/c/3", pre)
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)
    tree3 = sibling_worktree(repo, "spec/c/3", tmp_path)

    def derives(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree2, "spec/c/2", new_base="main", old_base=pre, resolve=derives, context=context()
    )

    with pytest.raises(RestackConflict):
        move_branch_onto(tree3, "spec/c/3", new_base="main", old_base=pre)

    assert not rebase_in_progress(tree3)
    assert git(tree3, "status", "--porcelain") == ""
