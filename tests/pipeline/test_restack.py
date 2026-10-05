"""Moving a stack after review or a merge.

When a lower PR gains a commit, or merges, everything above it has to move.
This is the riskiest code in the pipeline: it rewrites branches that already
exist on the remote, so the tests run against real git repositories and a real
remote rather than asserting on command strings.

Two failures matter more than the rest, and both have bitten already:

- **A push that overwrites a commit somebody else made.** Verified against
  git-branchless: its submit force-pushes with a bare lease after fetching in
  the same command, so the lease compares against a ref it just advanced, and
  it overwrote a concurrent commit while reporting success.
- **A conflict resolved by guessing.** A restack that silently drops or
  mangles a change is worse than one that stops and says so.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline import restack
from agent_build_kit.pipeline.restack import (
    RestackConflict,
    StaleRemote,
    adopt_host_head,
    move_branch_onto,
    push_with_lease,
)
from tests.factories import activate_with, git, init_repo


def commit(repo: Path, name: str, content: str = "x") -> None:
    (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"add {name}")


@pytest.fixture
def stack(tmp_path: Path) -> Path:
    """main → spec/c/1 (parent) → spec/c/2 (child), plus a remote."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)

    repo = init_repo(tmp_path / "repo")
    git(repo, "remote", "add", "origin", str(remote))
    commit(repo, "base.txt")
    git(repo, "push", "-q", "-u", "origin", "main")

    git(repo, "checkout", "-q", "-b", "spec/c/1")
    commit(repo, "parent.txt")
    git(repo, "checkout", "-q", "-b", "spec/c/2")
    commit(repo, "child.txt")
    git(repo, "checkout", "-q", "main")
    return repo


def test_a_child_moves_onto_main_after_its_parent_merges(stack: Path) -> None:
    """The parent's commits arrive via main, so replaying them would duplicate
    them; the child keeps only its own."""
    git(stack, "merge", "-q", "--no-ff", "-m", "merge parent", "spec/c/1")

    move_branch_onto(stack, "spec/c/2", new_base="main", old_base="spec/c/1")

    log = git(stack, "log", "--oneline", "main..spec/c/2")
    assert "child.txt" in log
    assert "parent.txt" not in log


def test_the_childs_work_survives_the_move(stack: Path) -> None:
    git(stack, "merge", "-q", "--no-ff", "-m", "merge parent", "spec/c/1")

    move_branch_onto(stack, "spec/c/2", new_base="main", old_base="spec/c/1")

    git(stack, "checkout", "-q", "spec/c/2")
    assert (stack / "child.txt").exists()
    assert (stack / "parent.txt").exists(), "still present, now via main"


def test_a_conflict_stops_rather_than_guessing(stack: Path) -> None:
    """A restack that silently mangles a change is worse than one that stops."""
    git(stack, "checkout", "-q", "main")
    commit(stack, "child.txt", "different content on main")

    with pytest.raises(RestackConflict):
        move_branch_onto(stack, "spec/c/2", new_base="main", old_base="spec/c/1")


def test_a_conflict_leaves_no_rebase_in_progress(stack: Path) -> None:
    """A half-finished rebase would break every later run in this worktree."""
    git(stack, "checkout", "-q", "main")
    commit(stack, "child.txt", "different content on main")

    with pytest.raises(RestackConflict):
        move_branch_onto(stack, "spec/c/2", new_base="main", old_base="spec/c/1")

    assert not (stack / ".git" / "rebase-merge").exists()
    assert not (stack / ".git" / "rebase-apply").exists()


def test_a_first_push_needs_no_force(stack: Path) -> None:
    """Nothing to overwrite yet, and a force on a fresh branch would hide a
    naming mistake rather than surface it."""
    sha = push_with_lease(stack, "spec/c/1", last_pushed=None)

    assert sha == git(stack, "rev-parse", "spec/c/1")
    assert "spec/c/1" in git(stack, "branch", "-r")


def test_a_rewritten_branch_pushes_with_an_explicit_lease(stack: Path) -> None:
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    git(stack, "checkout", "-q", "spec/c/1")
    commit(stack, "more.txt")

    push_with_lease(stack, "spec/c/1", last_pushed=pushed)

    assert git(stack, "log", "--oneline", "origin/spec/c/1").count("\n") >= 1


def test_a_push_refuses_when_somebody_else_moved_the_branch(stack: Path, tmp_path: Path) -> None:
    """The exact case the explicit lease exists for: a commit pushed from
    elsewhere must never be overwritten, even though the runner has fetched
    since."""
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)

    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "remote.git"), str(other)], check=True)
    git(other, "config", "user.email", "o@o.o")
    git(other, "config", "user.name", "o")
    git(other, "checkout", "-q", "spec/c/1")
    commit(other, "theirs.txt")
    git(other, "push", "-q", "origin", "spec/c/1")

    git(stack, "checkout", "-q", "spec/c/1")
    commit(stack, "ours.txt")
    git(stack, "fetch", "-q", "origin")  # the fetch that defeats a bare lease

    with pytest.raises(StaleRemote):
        push_with_lease(stack, "spec/c/1", last_pushed=pushed)

    assert "theirs.txt" in git(stack, "show", "--name-only", "origin/spec/c/1")


def _host_rebases(tmp_path: Path, branch: str) -> str:
    """What the host does after a stack merge: rebase the branch onto a trunk
    that has moved on, and force-push it from somewhere that is not this
    checkout. The branch then carries trunk commits that are not its own.
    Returns the new head."""
    other = tmp_path / "host"
    # `-b`: the bare remote's HEAD names the machine's default branch, which
    # is not always `main`, and a clone of a dangling HEAD checks nothing out.
    subprocess.run(
        ["git", "clone", "-q", "-b", "main", str(tmp_path / "remote.git"), str(other)], check=True
    )
    git(other, "config", "user.email", "o@o.o")
    git(other, "config", "user.name", "o")
    commit(other, "trunk.txt", "landed on the trunk meanwhile")
    git(other, "push", "-q", "origin", "main")
    git(other, "checkout", "-q", branch)
    git(other, "rebase", "-q", "main")
    git(other, "push", "-q", "--force", "origin", branch)
    return git(other, "rev-parse", "HEAD").strip()


def test_the_host_s_head_is_read_where_branches_are_pushed(
    stack: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not `origin`: the lease is checked against `push_target`, and where the
    two differ `origin` may not answer at all."""
    push_with_lease(stack, "spec/c/1", last_pushed=None)
    git(stack, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
    monkeypatch.setattr(restack, "push_target", lambda repo: str(tmp_path / "remote.git"))

    assert restack.remote_head(stack, "spec/c/1") == git(stack, "rev-parse", "spec/c/1").strip()


def test_a_branch_the_host_moved_is_brought_to_the_host_s_head(stack: Path, tmp_path: Path) -> None:
    """So review judges what the host has, and the next lease names it."""
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    host_head = _host_rebases(tmp_path, "spec/c/1")

    adopted = adopt_host_head(stack, "spec/c/1", host_head=host_head, last_pushed=pushed, cwd=stack)

    assert adopted == host_head
    assert git(stack, "rev-parse", "spec/c/1").strip() == host_head
    assert "trunk.txt" in git(stack, "show", "--name-only", "spec/c/1~1"), "the host's rebase"
    push_with_lease(stack, "spec/c/1", last_pushed=host_head)  # the lease now holds


def test_a_branch_already_at_the_host_s_head_is_left_alone(stack: Path) -> None:
    """A push whose recording was lost: the store's last push is older than
    both. Nothing is replayed, and nothing is refused."""
    before = git(stack, "rev-parse", "main").strip()
    head = push_with_lease(stack, "spec/c/1", last_pushed=None)

    adopted = adopt_host_head(stack, "spec/c/1", host_head=head, last_pushed=before, cwd=stack)

    assert adopted == head
    assert git(stack, "rev-parse", "spec/c/1").strip() == head


def test_work_not_yet_pushed_is_kept_on_top_of_the_host_s_head(stack: Path, tmp_path: Path) -> None:
    """A rework committed here since the last push is replayed, not dropped."""
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    host_head = _host_rebases(tmp_path, "spec/c/1")
    git(stack, "checkout", "-q", "spec/c/1")
    commit(stack, "rework.txt")

    adopt_host_head(stack, "spec/c/1", host_head=host_head, last_pushed=pushed, cwd=stack)

    assert git(stack, "rev-parse", "spec/c/1~1").strip() == host_head
    assert (stack / "rework.txt").exists()


def _host_clone(tmp_path: Path, branch: str) -> Path:
    other = tmp_path / "host"
    subprocess.run(
        ["git", "clone", "-q", "-b", "main", str(tmp_path / "remote.git"), str(other)], check=True
    )
    git(other, "config", "user.email", "o@o.o")
    git(other, "config", "user.name", "o")
    git(other, "checkout", "-q", branch)
    return other


def _host_rewords(tmp_path: Path, branch: str) -> str:
    """The host rewrites the branch's tip to a different commit carrying the
    same change (a message edited, as when a trailer is dropped) and
    force-pushes it. Returns the new head."""
    other = _host_clone(tmp_path, branch)
    git(other, "commit", "-q", "--amend", "-m", "reworded by a person")
    git(other, "push", "-q", "--force", "origin", branch)
    return git(other, "rev-parse", "HEAD").strip()


def _restack_onto_a_newer_trunk(repo: Path, branch: str, tmp_path: Path) -> None:
    """The trunk moves on the remote only, as it does for a real installation:
    the local `main` is the user's and stays behind, and the branch is rebased
    onto `origin/main`."""
    other = tmp_path / "trunk-host"
    subprocess.run(
        ["git", "clone", "-q", "-b", "main", str(tmp_path / "remote.git"), str(other)], check=True
    )
    git(other, "config", "user.email", "o@o.o")
    git(other, "config", "user.name", "o")
    commit(other, "trunk.txt", "landed on the trunk meanwhile")
    git(other, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    git(repo, "rebase", "-q", "origin/main", branch)
    git(repo, "checkout", "-q", "main")


def test_a_branch_the_host_rewrote_without_changing_the_work_is_adopted(
    stack: Path, tmp_path: Path
) -> None:
    """Same change at different commits: the approved head stays, and the
    caller records the host's head so the lease matches."""
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    host_head = _host_rewords(tmp_path, "spec/c/1")
    assert host_head != pushed

    adopt_host_head(
        stack, "spec/c/1", host_head=host_head, last_pushed=pushed, cwd=stack, base="origin/main"
    )

    assert git(stack, "rev-parse", "spec/c/1").strip() == pushed, "nothing reset or replayed"


def test_a_restacked_local_branch_over_the_hosts_older_form_replays_nothing(
    stack: Path, tmp_path: Path
) -> None:
    """The recorded push is no ancestor of the restacked branch, so counting
    commits after it would replay the trunk's and the unit's own."""
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    host_head = _host_rewords(tmp_path, "spec/c/1")
    _restack_onto_a_newer_trunk(stack, "spec/c/1", tmp_path)
    restacked = git(stack, "rev-parse", "spec/c/1").strip()

    adopt_host_head(
        stack, "spec/c/1", host_head=host_head, last_pushed=pushed, cwd=stack, base="origin/main"
    )

    assert git(stack, "rev-parse", "spec/c/1").strip() == restacked


def test_only_the_work_the_host_lacks_is_replayed_after_a_restack(
    stack: Path, tmp_path: Path
) -> None:
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    host_head = _host_rewords(tmp_path, "spec/c/1")
    _restack_onto_a_newer_trunk(stack, "spec/c/1", tmp_path)
    git(stack, "checkout", "-q", "spec/c/1")
    commit(stack, "rework.txt")

    adopt_host_head(
        stack, "spec/c/1", host_head=host_head, last_pushed=pushed, cwd=stack, base="origin/main"
    )

    assert git(stack, "rev-parse", "spec/c/1~1").strip() == host_head
    assert (stack / "rework.txt").exists()
    assert not (stack / "trunk.txt").exists(), "the trunk's commit is not the unit's work"


def test_a_host_change_that_does_not_combine_with_local_work_is_refused(
    stack: Path, tmp_path: Path
) -> None:
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    other = _host_clone(tmp_path, "spec/c/1")
    commit(other, "parent.txt", "the host's edit")
    git(other, "push", "-q", "origin", "spec/c/1")
    host_head = git(other, "rev-parse", "HEAD").strip()
    git(stack, "checkout", "-q", "spec/c/1")
    commit(stack, "parent.txt", "our edit")
    ours = git(stack, "rev-parse", "spec/c/1").strip()

    with pytest.raises(StaleRemote, match=host_head[:9]):
        adopt_host_head(
            stack,
            "spec/c/1",
            host_head=host_head,
            last_pushed=pushed,
            cwd=stack,
            base="origin/main",
        )

    assert git(stack, "rev-parse", "spec/c/1").strip() == ours, "nothing is changed"


def test_a_host_head_that_descends_from_the_last_push_still_gets_local_work_replayed(
    stack: Path, tmp_path: Path
) -> None:
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    other = _host_clone(tmp_path, "spec/c/1")
    commit(other, "theirs.txt")
    git(other, "push", "-q", "origin", "spec/c/1")
    host_head = git(other, "rev-parse", "HEAD").strip()
    git(stack, "checkout", "-q", "spec/c/1")
    commit(stack, "rework.txt")

    adopt_host_head(
        stack, "spec/c/1", host_head=host_head, last_pushed=pushed, cwd=stack, base="origin/main"
    )

    assert git(stack, "rev-parse", "spec/c/1~1").strip() == host_head
    assert (stack / "rework.txt").exists()


def test_a_local_commit_the_host_already_holds_is_not_replayed(stack: Path, tmp_path: Path) -> None:
    """The host added what one unpushed local commit adds: replaying it would
    stop as empty, so only the commit the host lacks goes on top."""
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    other = _host_clone(tmp_path, "spec/c/1")
    commit(other, "rework.txt")
    git(other, "push", "-q", "origin", "spec/c/1")
    host_head = git(other, "rev-parse", "HEAD").strip()
    git(stack, "checkout", "-q", "spec/c/1")
    commit(stack, "rework.txt")
    commit(stack, "more.txt")

    adopt_host_head(
        stack, "spec/c/1", host_head=host_head, last_pushed=pushed, cwd=stack, base="origin/main"
    )

    assert git(stack, "rev-parse", "spec/c/1~1").strip() == host_head
    assert (stack / "more.txt").exists()


def test_a_dirty_worktree_is_refused_rather_than_reset(stack: Path, tmp_path: Path) -> None:
    pushed = push_with_lease(stack, "spec/c/1", last_pushed=None)
    host_head = _host_rebases(tmp_path, "spec/c/1")
    git(stack, "checkout", "-q", "spec/c/1")
    (stack / "parent.txt").write_text("uncommitted edit")

    with pytest.raises(StaleRemote, match="uncommitted"):
        adopt_host_head(
            stack,
            "spec/c/1",
            host_head=host_head,
            last_pushed=pushed,
            cwd=stack,
            base="origin/main",
        )

    assert (stack / "parent.txt").read_text() == "uncommitted edit"
    assert git(stack, "rev-parse", "spec/c/1").strip() == pushed


def test_a_stacked_unit_keeps_only_its_own_rework_when_the_host_squashes_its_parent(
    stack: Path, tmp_path: Path
) -> None:
    """The host squash-merges the parent and rebases the child onto the trunk.
    The child's unpushed rework is replayed on the host's head; the parent's
    commits, which the host now holds as one, are not."""
    git(stack, "checkout", "-q", "spec/c/1")
    commit(stack, "parent2.txt")
    git(stack, "checkout", "-q", "spec/c/2")
    git(stack, "rebase", "-q", "spec/c/1")
    pushed = push_with_lease(stack, "spec/c/2", last_pushed=None)
    push_with_lease(stack, "spec/c/1", last_pushed=None)

    other = _host_clone(tmp_path, "spec/c/2")
    git(other, "checkout", "-q", "main")
    git(other, "merge", "-q", "--squash", "origin/spec/c/1")
    git(other, "commit", "-qm", "parent squashed")
    git(other, "push", "-q", "origin", "main")
    git(other, "checkout", "-q", "spec/c/2")
    git(other, "rebase", "-q", "--onto", "main", "origin/spec/c/1")
    git(other, "push", "-q", "--force", "origin", "spec/c/2")
    host_head = git(other, "rev-parse", "HEAD").strip()
    git(stack, "fetch", "-q", "origin")
    git(stack, "checkout", "-q", "spec/c/2")
    commit(stack, "rework.txt")

    adopt_host_head(
        stack, "spec/c/2", host_head=host_head, last_pushed=pushed, cwd=stack, base="origin/main"
    )

    assert git(stack, "rev-parse", "spec/c/2~1").strip() == host_head
    assert (stack / "rework.txt").exists()


def test_a_blast_radius_note_says_what_moved_and_why() -> None:
    """A reviewer seeing a force-push needs to know what changed underneath
    without diffing the branch against its old self."""
    from agent_build_kit.pipeline.restack import blast_radius_note

    note = blast_radius_note(
        branch="spec/c/2", old_base="spec/c/1", new_base="main", reason="parent merged"
    )

    assert "spec/c/2" in note
    assert "spec/c/1" in note
    assert "main" in note
    assert "parent merged" in note


def test_agent_branches_push_through_the_configured_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pipeline pushes as its own GitHub account, not as whoever owns the
    default ssh key. Rewriting origin's host is what routes it through the
    alias carrying that account's key."""
    activate_with(git={"push_host": "github-example"})
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:example/app.git"],
        cwd=repo,
        check=True,
    )

    assert restack.push_target(repo) == "git@github-example:example/app.git"


def test_without_one_configured_it_pushes_to_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset is the working default: whatever the checkout already pushes to."""
    activate_with(git={"push_host": ""})

    assert restack.push_target(tmp_path) == "origin"


def test_an_https_origin_is_left_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Only an ssh remote can be routed through an ssh alias. Mangling an
    https one would produce a URL that fails at push time, after the unit has
    already been built and reviewed locally."""
    activate_with(git={"push_host": "github-example"})
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/example/app.git"],
        cwd=repo,
        check=True,
    )

    assert restack.push_target(repo) == "origin"


def build_stack(tmp_path: Path) -> Path:
    """main <- spec/c/1 <- spec/c/2, each touching a different file."""
    repo = tmp_path / "stack"
    repo.mkdir()
    init_repo(repo)

    def commit(name: str) -> None:
        (repo / name).write_text(name)
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", name], cwd=repo, check=True)

    commit("base.txt")
    subprocess.run(["git", "checkout", "-q", "-b", "spec/c/1"], cwd=repo, check=True)
    commit("one.txt")
    subprocess.run(["git", "checkout", "-q", "-b", "spec/c/2"], cwd=repo, check=True)
    commit("two.txt")
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True)
    return repo


def test_a_resolved_move_tells_the_resolver_both_intents(tmp_path: Path) -> None:
    """The one thing both callers must not get wrong. A resolver given only the
    diff has to guess which side to keep, and the cheapest way to end a conflict
    is to delete one — so the intents are what make a resolution checkable."""
    seen: dict = {}

    restack.resolved_move(
        tmp_path,
        "spec/c/2",
        new_base="spec/c/1",
        old_base="abc123",
        moving_unit="c/2",
        moving_intent="relay the event",
        onto_unit="c/1",
        onto_intent="publish the event",
        move=lambda repo, branch, **kw: seen.update(kw) or restack.Moved(sha="sha"),
    )

    assert seen["resolve"] is restack.claude_resolver
    assert seen["context"].moving_intent == "relay the event"
    assert seen["context"].onto_intent == "publish the event"
    assert seen["new_base"] == "spec/c/1"
    assert seen["old_base"] == "abc123"
