"""Each agent run has its own ignored scratch folder for long command output.

The folder is `<worktree>/.abk/out/<run>/`: git never sees it (the worktree's
local exclude file names it, no tracked ignore file changes), a run's files are
its own and are gone when it ends, and nothing one agent wrote reaches another
agent or stands in for tier 1's own run (spec: command-output-to-files).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline import scratch as scratch_module
from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.restack import claude_resolver
from agent_build_kit.pipeline.scratch import cap_files, remove_leftovers, run_folder
from agent_build_kit.pipeline.wiring import (
    REVIEW_PROMPT,
    build_commit,
    build_run,
    build_run_review,
    build_tier1,
)
from agent_build_kit.pipeline.workspaces import prepare_worktree
from agent_build_kit.runtimes import AgentInterrupted, AgentRateLimited, AgentRequest
from tests.factories import git, init_repo, stored_unit
from tests.runtimes.stand_in import StandInRuntime

MODEL = "m"

BRANCH = "spec/change/1"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


@pytest.fixture
def tree(repo: Path, tmp_path: Path) -> Path:
    return prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees")


def scratch(tree: Path) -> Path:
    return tree / ".abk" / "out"


def exclude_lines(tree: Path) -> list[str]:
    path = Path(git(tree, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"))
    return [line.strip() for line in path.read_text().splitlines() if line.strip() == ".abk/"]


def out_of(request: AgentRequest) -> Path:
    return Path(request.env["ABK_OUT"])


# --- the worktree carries the folder and its exclude line ---------------------------


def test_a_new_worktree_has_the_scratch_folder_and_excludes_it(tree: Path) -> None:
    assert scratch(tree).is_dir()
    assert exclude_lines(tree) == [".abk/"]


def test_the_exclude_line_is_added_once_however_often_the_worktree_is_prepared(
    repo: Path, tree: Path, tmp_path: Path
) -> None:
    prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees")
    other = prepare_worktree(repo, "spec/change/2", base="main", root=tmp_path / "trees")

    assert scratch(other).is_dir()
    assert exclude_lines(tree) == [".abk/"]
    assert exclude_lines(other) == [".abk/"]


def test_git_sees_nothing_in_the_scratch_folder(tree: Path, repo: Path, tmp_path: Path) -> None:
    (scratch(tree) / "run-1").mkdir()
    (scratch(tree) / "run-1" / "suite.log").write_text("1 passed\n")

    assert git(tree, "status", "--porcelain") == ""
    git(tree, "add", "-A")
    assert git(tree, "diff", "--cached", "--name-only") == ""
    # Still a clean worktree, so a re-run reuses it rather than refusing it.
    prepare_worktree(repo, BRANCH, base="main", root=tmp_path / "trees")


def test_the_leftover_commit_stages_nothing_from_the_scratch_folder(tree: Path) -> None:
    (scratch(tree) / "run-1").mkdir()
    (scratch(tree) / "run-1" / "suite.log").write_text("1 passed\n")

    assert build_commit()("nothing but scratch", cwd=tree) == 0

    (tree / "marker.py").write_text("MARKER = 1\n")
    assert build_commit()("a real file", cwd=tree) == 1
    assert git(tree, "show", "--name-only", "--format=", "HEAD").split() == ["marker.py"]


# --- a run's folder ------------------------------------------------------------------


def record_folders(runtime_log: list[tuple[Path, list[str]]]) -> Callable[[AgentRequest], None]:
    """What a run found in its folder when it started."""

    def act(request: AgentRequest) -> None:
        folder = out_of(request)
        runtime_log.append((folder, sorted(entry.name for entry in folder.iterdir())))

    return act


def test_a_run_gets_a_folder_of_its_own_in_the_scratch_folder_and_is_told_where(
    tree: Path,
) -> None:
    seen: list[tuple[Path, list[str]]] = []
    runtime = StandInRuntime(act=record_folders(seen))

    build_run(runtime=runtime)("Implement it.", cwd=tree, model=MODEL)

    [(folder, found)] = seen
    assert folder.parent.resolve() == scratch(tree).resolve()
    assert found == []


@pytest.mark.parametrize(
    "runtime_for",
    [
        pytest.param(lambda act: StandInRuntime(act=act), id="completed"),
        pytest.param(lambda act: StandInRuntime(act=act, ok=False, error="boom"), id="failed"),
    ],
)
def test_a_run_s_folder_is_removed_when_it_ends_in_an_outcome_that_returns(
    tree: Path, runtime_for: Callable[[Callable[[AgentRequest], None]], StandInRuntime]
) -> None:
    folders: list[Path] = []

    def act(request: AgentRequest) -> None:
        folders.append(out_of(request))
        (out_of(request) / "suite.log").write_text("1 passed\n")

    try:
        build_run(runtime=runtime_for(act))("Implement it.", cwd=tree, model=MODEL)
    except RuntimeError:
        pass

    [folder] = folders
    assert not folder.exists()
    assert list(scratch(tree).iterdir()) == []


@pytest.mark.parametrize("raised", [AgentInterrupted, AgentRateLimited])
def test_a_run_s_folder_is_removed_when_it_is_interrupted_or_rate_limited(
    tree: Path, raised: type[Exception]
) -> None:
    folders: list[Path] = []

    def act(request: AgentRequest) -> None:
        folders.append(out_of(request))
        (out_of(request) / "suite.log").write_text("1 passed\n")
        raise raised("stopped")

    with pytest.raises(raised):
        build_run(runtime=StandInRuntime(act=act))("Implement it.", cwd=tree, model=MODEL)

    [folder] = folders
    assert not folder.exists()


def test_a_folder_left_by_a_killed_run_is_removed_when_the_unit_next_starts_a_run(
    tree: Path,
) -> None:
    killed = scratch(tree) / "killed-run"
    killed.mkdir()
    (killed / "suite.log").write_text("left behind\n")
    seen: list[tuple[Path, list[str]]] = []

    build_run(runtime=StandInRuntime(act=record_folders(seen)))(
        "Implement it.", cwd=tree, model=MODEL
    )

    assert not killed.exists()
    [(_, found)] = seen
    assert found == []


def test_folders_left_in_a_worktree_are_removed_by_the_sweep(tree: Path) -> None:
    for name in ("run-1", "run-2"):
        (scratch(tree) / name).mkdir()
        (scratch(tree) / name / "suite.log").write_text("left behind\n")

    remove_leftovers(tree)

    assert list(scratch(tree).iterdir()) == []
    assert git(tree, "status", "--porcelain") == ""


def test_a_folder_left_by_a_killed_run_is_removed_when_its_change_is_archived(
    tree: Path, tmp_path: Path
) -> None:
    killed = scratch(tree) / "killed-run"
    killed.mkdir()
    (killed / "suite.log").write_text("left behind\n")
    (tmp_path / "planning" / "openspec" / "changes" / "change").mkdir(parents=True)
    asked: list[str] = []

    def worktrees(change: str) -> list[Path]:
        asked.append(change)
        return [tree]

    def runner(args: list[str], *, cwd: Path, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, 0, "archived\n", "")

    archive_ready_changes(
        [stored_unit("change/1", change="change", state="merged")],
        planning_repo=tmp_path / "planning",
        run=runner,
        worktrees=worktrees,
    )

    assert asked == ["change"]
    assert not killed.exists()


# --- the size cap ---------------------------------------------------------------------


def test_a_file_past_the_cap_is_cut_to_its_tail_with_a_marker(tmp_path: Path) -> None:
    folder = tmp_path / "out"
    folder.mkdir()
    lines = [f"line {number:05d}\n" for number in range(5000)]
    (folder / "suite.log").write_text("".join(lines))
    (folder / "small.log").write_text("short\n")

    cap_files(folder, max_bytes=2000)

    text = (folder / "suite.log").read_text()
    assert "truncated" in text.lower()
    assert text.endswith(lines[-1])
    assert lines[-20] in text
    assert lines[0] not in text
    assert len(text.encode()) < 2000 + 500, "the cap, plus room for the marker"
    assert (folder / "small.log").read_text() == "short\n"


def wait_until(condition: Callable[[], bool], seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return condition()


def test_a_live_run_s_file_is_held_to_the_cap_even_while_its_writer_has_it_open(
    tree: Path,
) -> None:
    cap = 2000
    seen: list[tuple[bool, bool, bytes]] = []

    def act(request: AgentRequest) -> None:
        big = out_of(request) / "big.log"
        lines = [f"line {number:05d}\n".encode() for number in range(2000)]
        # A plain `>`: the writer keeps its offset when the file is cut.
        with big.open("wb") as writer:
            for batch in (lines[:1000], lines[1000:]):
                writer.write(b"".join(batch))
                writer.flush()

                def settled(last: bytes = batch[-1]) -> bool:
                    # The write can reach the file in pieces, with a pass between them:
                    # wait for the whole batch to land and be cut, not just a small file.
                    text = big.read_bytes()
                    return len(text) <= cap + 500 and b"\0" not in text and last in text

                held = wait_until(settled)
                text = big.read_bytes()
                seen.append((held, b"\0" not in text and batch[-1] in text, text))

    with run_folder(tree, max_bytes=cap, interval=0.02) as out:
        assert out is not None
        act(AgentRequest(prompt="", cwd=tree, env={"ABK_OUT": str(out)}))

    assert [(held, intact) for held, intact, _ in seen] == [(True, True), (True, True)]
    assert b"truncated" in seen[0][2]


def test_a_run_through_the_build_step_has_its_files_capped_while_it_goes(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(scratch_module, "MAX_BYTES", 2000)
    monkeypatch.setattr(scratch_module, "CAP_INTERVAL", 0.02)
    sizes: list[int] = []

    def act(request: AgentRequest) -> None:
        big = out_of(request) / "big.log"
        big.write_text("".join(f"line {number:05d}\n" for number in range(2000)))
        wait_until(lambda: big.stat().st_size <= 2500)
        sizes.append(big.stat().st_size)

    build_run(runtime=StandInRuntime(act=act))("Implement it.", cwd=tree, model=MODEL)

    assert sizes and sizes[0] <= 2500


# --- the conflict resolver has a folder of its own too -----------------------------------


@pytest.mark.parametrize("ok", [True, False])
def test_the_conflict_resolver_gets_a_folder_that_is_gone_when_it_ends(
    tree: Path, ok: bool
) -> None:
    folders: list[Path] = []

    def act(request: AgentRequest) -> None:
        folder = out_of(request)
        assert folder.is_dir()
        assert folder.parent.resolve() == scratch(tree).resolve()
        (folder / "suite.log").write_text("1 passed\n")
        folders.append(folder)

    runtime = StandInRuntime(act=act, ok=ok, error="" if ok else "boom")
    try:
        claude_resolver("Resolve it.", cwd=tree, runtime=runtime)
    except RuntimeError:
        assert not ok

    [folder] = folders
    assert not folder.exists()
    assert list(scratch(tree).iterdir()) == []


# --- agents do not share output --------------------------------------------------------


def test_a_build_a_rework_and_a_review_each_start_in_a_new_empty_folder(tree: Path) -> None:
    sentinel = "SENTINEL-BUILDER-SUITE-OUTPUT"
    runs: dict[str, tuple[Path, list[str]]] = {}
    prompts: dict[str, str] = {}

    def acting(role: str, write: bool) -> Callable[[AgentRequest], None]:
        def act(request: AgentRequest) -> None:
            folder = out_of(request)
            runs[role] = (folder, sorted(entry.name for entry in folder.iterdir()))
            prompts[role] = request.prompt
            if write:
                (folder / "suite.log").write_text(f"{sentinel}\n")

        return act

    build = build_run(runtime=StandInRuntime(act=acting("build", True), answer=sentinel))
    rework = build_run(runtime=StandInRuntime(act=acting("rework", True)))
    review = build_run_review(runtime=StandInRuntime(act=acting("review", False)))

    build("Implement it.", cwd=tree, model=MODEL)
    rework("Fix it.", cwd=tree, model=MODEL)
    review(cwd=tree)

    folders = {role: folder for role, (folder, _) in runs.items()}
    assert len(set(folders.values())) == 3
    assert all(found == [] for _, found in runs.values()), runs
    assert not any(folder.exists() for folder in folders.values())
    assert sentinel not in prompts["review"]
    assert sentinel not in prompts["rework"]


def test_the_reviewer_is_told_to_run_its_own_commands() -> None:
    prompt = " ".join(REVIEW_PROMPT.split()).lower()

    assert "own commands" in prompt


def test_tier_1_runs_the_suite_itself_whatever_an_agent_left(tree: Path) -> None:
    left = scratch(tree) / "run-1"
    left.mkdir()
    (left / "suite.exit").write_text("0\n")
    (left / "suite.log").write_text("1 passed\n")
    (tree / "tests").mkdir()
    (tree / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    ran: list[list[str]] = []

    def run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        ran.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    passed, _ = build_tier1(run=run, changed=lambda *a: ["tests/test_x.py"])(cwd=tree, base="main")

    assert passed
    assert any("pytest" in " ".join(command) for command in ran)
    assert list(scratch(tree).iterdir()) == [left], (
        "tier 1 neither reads nor clears an agent's folder"
    )
