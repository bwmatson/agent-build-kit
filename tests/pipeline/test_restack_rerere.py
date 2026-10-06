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

from agent_build_kit.pipeline import restack, shell
from agent_build_kit.pipeline.restack import (
    ConflictContext,
    RestackConflict,
    conflicted_files,
    move_branch_onto,
)
from tests.factories import git, init_repo


@pytest.fixture(autouse=True)
def isolated_git_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """None of this module's assertions about global git config mean anything
    against the developer's real one: without this, a machine with
    `rerere.enabled=true` set globally would pass every replay test here even
    with the `-c` flags deleted from `restack.git`, since rerere would already
    be on regardless."""
    config_path = tmp_path_factory.mktemp("gitconfig") / "gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config_path))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return config_path


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
    assert git(tree3, "show", "spec/c/3:conflicted.py") == "value = 2  # sibling"
    assert not rebase_in_progress(tree3)


def note_files(prompt: str) -> str:
    """The list of paths under the replayed-resolution note, or "" if the
    prompt carries no such note."""
    marker = "still unstaged for you to judge:\n"
    if marker not in prompt:
        return ""
    after = prompt.split(marker, 1)[1]
    return after.split("\nLeave one unchanged", 1)[0]


def test_the_resolver_is_told_only_the_paths_with_a_replayed_resolution(
    tmp_path: Path,
) -> None:
    """Two conflicted files, and only one of them has a recorded resolution —
    the note must name that one and not the other."""

    def commit_both(conflicted_value: str, other_value: str) -> None:
        # One commit for both files: a rebase that has to replay two
        # separate commits would hit a second conflict of its own once
        # `move_branch_onto` continues past the first, which is a different
        # scenario than what this test means to set up.
        (repo / "conflicted.py").write_text(conflicted_value)
        (repo / "other.py").write_text(other_value)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "write both files")

    repo = init_repo(tmp_path / "repo")
    commit_both("value = 1\n", "value = 1\n")
    pre = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "spec/c/1")
    commit_both("value = 2  # predecessor\n", "value = 2  # predecessor\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge predecessor", "spec/c/1")

    def make_sibling(name: str, other_value: str) -> None:
        git(repo, "checkout", "-q", "-b", name, pre)
        commit_both("value = 1  # sibling\n", other_value)
        git(repo, "checkout", "-q", "main")

    # other.py's own committed content differs per sibling, so its conflict
    # never matches a cached entry — only conflicted.py's does.
    make_sibling("spec/c/2", "value = 1  # sibling-two\n")
    make_sibling("spec/c/3", "value = 1  # sibling-three\n")
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)
    tree3 = sibling_worktree(repo, "spec/c/3", tmp_path)

    def derives(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")
        (cwd / "other.py").write_text("value = 2  # sibling-two\n")

    move_branch_onto(
        tree2, "spec/c/2", new_base="main", old_base=pre, resolve=derives, context=context()
    )

    seen: dict = {}

    def confirms(prompt: str, *, cwd: Path) -> None:
        seen["prompt"] = prompt
        # Still unmerged and unstaged when the resolver is handed it — a
        # replayed resolution is a proposal, not something already accepted.
        seen["conflicted_at_arrival"] = conflicted_files(cwd)
        (cwd / "other.py").write_text("value = 2  # sibling-three\n")

    move_branch_onto(
        tree3, "spec/c/3", new_base="main", old_base=pre, resolve=confirms, context=context()
    )

    assert "conflicted.py" in seen["conflicted_at_arrival"]
    assert "other.py" in seen["conflicted_at_arrival"]
    note = note_files(seen["prompt"])
    assert "- conflicted.py" in note
    assert "- other.py" not in note


def test_a_first_time_conflict_has_markers_and_no_replayed_note(tmp_path: Path) -> None:
    """No cache yet: the resolver sees exactly what any conflict with nothing
    replayed has always looked like — markers in the file, and no note."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "conflicted.py", "value = 1\n")
    pre = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "-b", "spec/c/1")
    commit(repo, "conflicted.py", "value = 2  # predecessor\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge predecessor", "spec/c/1")
    sibling(repo, "spec/c/2", pre)
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)

    seen: dict = {}

    def confirms(prompt: str, *, cwd: Path) -> None:
        seen["prompt"] = prompt
        seen["content_on_arrival"] = (cwd / "conflicted.py").read_text()
        seen["diff"] = restack.git(cwd, "diff", check=False).stdout[:8000]
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree2, "spec/c/2", new_base="main", old_base=pre, resolve=confirms, context=context()
    )

    assert any(marker in seen["content_on_arrival"] for marker in restack.CONFLICT_MARKERS)
    assert "replayed" not in seen["prompt"].lower()
    assert seen["prompt"] == restack.RESOLVE_PROMPT.format(
        moving_unit="add-marker/2",
        moving_intent="register the local value",
        onto_unit="add-marker/1",
        onto_intent="register the predecessor's value",
        files="- conflicted.py",
        replayed="",
        diff=seen["diff"],
        changelog_rule="",
        changelog="",
    )


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


def test_a_resolver_that_rejects_a_replay_aborts_and_clears_the_cache(
    landed: tuple[Path, str], tmp_path: Path
) -> None:
    """A resolver that judges a replayed resolution wrong, and cannot
    reconcile it with what it is resolving, has no markers to leave in a file
    that already has none — so a marker it plants itself is read as a
    rejection. That must both stop the move and forget the bad cache entry,
    or the very next sibling would be offered the same rejected content."""
    repo, pre = landed
    sibling(repo, "spec/c/2", pre)
    sibling(repo, "spec/c/3", pre)
    sibling(repo, "spec/c/4", pre)
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)
    tree3 = sibling_worktree(repo, "spec/c/3", tmp_path)
    tree4 = sibling_worktree(repo, "spec/c/4", tmp_path)

    def derives(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree2, "spec/c/2", new_base="main", old_base=pre, resolve=derives, context=context()
    )

    def rejects(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("<<<<<<< rejecting the replay\n")

    with pytest.raises(RestackConflict):
        move_branch_onto(
            tree3, "spec/c/3", new_base="main", old_base=pre, resolve=rejects, context=context()
        )

    assert not rebase_in_progress(tree3)
    assert git(tree3, "status", "--porcelain") == ""

    seen: dict = {}

    def confirms(prompt: str, *, cwd: Path) -> None:
        seen["content_on_arrival"] = (cwd / "conflicted.py").read_text()
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree4, "spec/c/4", new_base="main", old_base=pre, resolve=confirms, context=context()
    )

    assert any(marker in seen["content_on_arrival"] for marker in restack.CONFLICT_MARKERS), (
        "the rejected entry should not have been replayed to the next sibling"
    )


def test_a_rejected_replay_is_forgotten_even_when_not_the_first_marked_file(
    tmp_path: Path,
) -> None:
    """Two files both carry a cached resolution; the resolver rejects both by
    planting a marker in each. Raising on the first marked file found would
    skip the `rerere forget` for the second, so the next sibling would still
    be offered the very resolution just judged wrong for that file — exactly
    what a rejected replay is meant to stop."""

    def commit_both(conflicted_value: str, other_value: str) -> None:
        (repo / "conflicted.py").write_text(conflicted_value)
        (repo / "other.py").write_text(other_value)
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "write both files")

    repo = init_repo(tmp_path / "repo")
    commit_both("value = 1\n", "value = 1\n")
    pre = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "spec/c/1")
    commit_both("value = 2  # predecessor\n", "value = 2  # predecessor\n")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge predecessor", "spec/c/1")

    def make_sibling(name: str) -> None:
        git(repo, "checkout", "-q", "-b", name, pre)
        commit_both("value = 1  # sibling\n", "value = 1  # sibling\n")
        git(repo, "checkout", "-q", "main")

    make_sibling("spec/c/2")
    make_sibling("spec/c/3")
    make_sibling("spec/c/4")
    tree2 = sibling_worktree(repo, "spec/c/2", tmp_path)
    tree3 = sibling_worktree(repo, "spec/c/3", tmp_path)
    tree4 = sibling_worktree(repo, "spec/c/4", tmp_path)

    def derives(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")
        (cwd / "other.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree2, "spec/c/2", new_base="main", old_base=pre, resolve=derives, context=context()
    )

    def rejects_both(prompt: str, *, cwd: Path) -> None:
        (cwd / "conflicted.py").write_text("<<<<<<< rejecting\n")
        (cwd / "other.py").write_text("<<<<<<< rejecting\n")

    with pytest.raises(RestackConflict):
        move_branch_onto(
            tree3,
            "spec/c/3",
            new_base="main",
            old_base=pre,
            resolve=rejects_both,
            context=context(),
        )

    assert not rebase_in_progress(tree3)
    assert git(tree3, "status", "--porcelain") == ""

    seen: dict = {}

    def confirms(prompt: str, *, cwd: Path) -> None:
        seen["conflicted"] = (cwd / "conflicted.py").read_text()
        seen["other"] = (cwd / "other.py").read_text()
        (cwd / "conflicted.py").write_text("value = 2  # sibling\n")
        (cwd / "other.py").write_text("value = 2  # sibling\n")

    move_branch_onto(
        tree4, "spec/c/4", new_base="main", old_base=pre, resolve=confirms, context=context()
    )

    assert any(marker in seen["conflicted"] for marker in restack.CONFLICT_MARKERS), (
        "the rejected entry for conflicted.py should not have been replayed"
    )
    assert any(marker in seen["other"] for marker in restack.CONFLICT_MARKERS), (
        "the rejected entry for other.py should not have been replayed either"
    )


def test_a_modify_delete_conflict_is_never_reported_as_a_replay(tmp_path: Path) -> None:
    """A conflict rerere cannot track at all — here, one side deletes the file
    the other modifies — leaves no markers either, for a wholly different
    reason than a replay: git just leaves the modified version in the tree.
    `git rerere remaining` still lists it, since it was never resolved by
    rerere, so it must never show up in the replayed note."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "file.txt", "original\n")
    pre = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "spec/c/1")
    git(repo, "rm", "-q", "file.txt")
    git(repo, "commit", "-qm", "remove file.txt")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge predecessor", "spec/c/1")

    git(repo, "checkout", "-q", "-b", "spec/c/2", pre)
    commit(repo, "file.txt", "modified by sibling\n")
    git(repo, "checkout", "-q", "main")

    seen: dict = {}

    def resolves(prompt: str, *, cwd: Path) -> None:
        seen["prompt"] = prompt
        seen["conflicted_at_arrival"] = conflicted_files(cwd)
        # git already left the modified version in the tree; keep it.

    move_branch_onto(
        repo, "spec/c/2", new_base="main", old_base=pre, resolve=resolves, context=context()
    )

    assert "file.txt" in seen["conflicted_at_arrival"]
    assert "replayed" not in seen["prompt"].lower()
    assert not rebase_in_progress(repo)
    assert git(repo, "status", "--porcelain") == ""


def test_a_binary_conflict_with_an_empty_cache_is_never_reported_as_a_replay(
    tmp_path: Path,
) -> None:
    """A binary conflict is three-staged, so it is never PUNTED, and rerere's
    own `handle_file` finds no marker hunks to record, so it never enters
    MERGE_RR either — it is simply absent from `git rerere remaining`, the
    same as every path that *was* replayed. With an empty cache that must
    still read as "nothing replayed", not "everything replayed"."""
    repo = init_repo(tmp_path / "repo")
    (repo / "file.bin").write_bytes(b"\x00original\x00")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "write file.bin")
    pre = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "spec/c/1")
    (repo / "file.bin").write_bytes(b"\x00predecessor\x00")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "predecessor edits file.bin")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "merge predecessor", "spec/c/1")

    git(repo, "checkout", "-q", "-b", "spec/c/2", pre)
    (repo / "file.bin").write_bytes(b"\x00sibling\x00")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "sibling edits file.bin")
    git(repo, "checkout", "-q", "main")

    seen: dict = {}

    def resolves(prompt: str, *, cwd: Path) -> None:
        seen["prompt"] = prompt
        (cwd / "file.bin").write_bytes(b"\x00resolved\x00")

    move_branch_onto(
        repo, "spec/c/2", new_base="main", old_base=pre, resolve=resolves, context=context()
    )

    assert note_files(seen["prompt"]) == ""
    assert not rebase_in_progress(repo)
    assert git(repo, "status", "--porcelain") == ""


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


def test_the_rebase_runs_with_the_live_environment_not_an_import_time_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The environment the rebase call runs under must be built at call time.
    A constant captured once at import would freeze out any environment
    change made afterwards — such as this module's own `isolated_git_config`
    fixture, which sets `GIT_CONFIG_GLOBAL` well after `restack` is imported."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "base.py", "base = 1\n")
    pre = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "spec/c/2", pre)
    commit(repo, "feature.py", "feature = 1\n")
    git(repo, "checkout", "-q", "main")
    commit(repo, "other.py", "other = 1\n")

    monkeypatch.setenv("GIT_COMMITTER_NAME", "restack-env-probe")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "probe@example.com")

    move_branch_onto(repo, "spec/c/2", new_base="main", old_base=pre)

    assert git(repo, "log", "-1", "--format=%cn", "spec/c/2") == "restack-env-probe"


def test_the_rebase_call_forces_lc_all_to_c(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_replayed_files` only matches an untranslated rerere notice, so
    whatever builds the rebase call's environment must still force LC_ALL=C —
    a guard independent of the locale actually installed on the machine
    running the test."""
    repo = init_repo(tmp_path / "repo")
    commit(repo, "base.py", "base = 1\n")
    pre = git(repo, "rev-parse", "HEAD")

    git(repo, "checkout", "-q", "-b", "spec/c/2", pre)
    commit(repo, "feature.py", "feature = 1\n")
    git(repo, "checkout", "-q", "main")
    commit(repo, "other.py", "other = 1\n")

    seen: dict = {}
    original = shell.git

    def spy(repo_arg, *args, **kwargs):
        if "--onto" in args:
            seen["env"] = kwargs.get("env")
        return original(repo_arg, *args, **kwargs)

    monkeypatch.setattr(shell, "git", spy)

    move_branch_onto(repo, "spec/c/2", new_base="main", old_base=pre)

    assert seen["env"] is not None
    assert seen["env"]["LC_ALL"] == "C"
    assert seen["env"]["LANGUAGE"] == "C"


def test_without_a_resolver_a_cached_resolution_still_aborts_cleanly(
    landed: tuple[Path, str], tmp_path: Path
) -> None:
    """A cached resolution changes what a resolver has to do, not whether
    `move_branch_onto` with no resolver at all still stops exactly as it does
    with an empty cache — this is `move_branch_onto`'s own no-resolver
    contract, not the path the pipeline actually takes to reach a conflict."""
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


def test_a_failing_resolver_aborts_cleanly_through_the_wired_up_path(
    landed: tuple[Path, str], tmp_path: Path
) -> None:
    """The port step never calls `move_branch_onto` directly — it goes through
    `build_restack_onto`, which always wires up `resolved_move` with a
    resolver. This is the path that actually reaches a conflict with a replay
    present, and it must see the same clean `RestackConflict` when the
    resolver fails, with nothing left mid-rebase for the port step to trip
    over."""
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

    def fails(prompt: str, *, cwd: Path) -> None:
        raise RuntimeError("the resolver blew up")

    with pytest.raises(RestackConflict):
        restack.resolved_move(
            tree3,
            "spec/c/3",
            new_base="main",
            old_base=pre,
            moving_unit="add-marker/3",
            moving_intent="register the local value",
            onto_unit="add-marker/1",
            onto_intent="register the predecessor's value",
            resolve=fails,
        )

    assert not rebase_in_progress(tree3)
    assert git(tree3, "status", "--porcelain") == ""
