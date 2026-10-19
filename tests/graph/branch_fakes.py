"""The stand-ins a per-group build is driven over a real git branch with: the unit's commits are
made and read with git in the runner's worktree, so a build can start from the commits an earlier
run left, and what a commit says can be read back from the branch."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Member
from agent_build_kit.pipeline.wiring import branch_commits, build_commit
from tests.factories import activate_with, git, stored_unit
from tests.graph.stub_loop_fakes import StubLoop
from tests.graph.test_build_path import build
from tests.graph.test_outside_commits_prompt import branch, land
from tests.graph.test_per_group_build import group_named

UNIT = "add-marker/1"
TRAILER = f"Unit: {UNIT}"
BASE = "origin/main"
Groups = Mapping[int, tuple[str, str]]  # number -> (title, "Done when" sentence or "")


def titled(*numbers: int) -> Groups:
    """Groups titled `G<number>`, none with a "Done when" sentence."""
    return {number: (f"G{number}", "") for number in numbers}


def write_tasks(tmp_path: Path, change: str, groups: Groups) -> None:
    """The change's tasks file in the planning repo, where titles and goals are read from."""
    path = tmp_path / "meta" / "openspec" / "changes" / change / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            f"## {n}. [app] [unit-test] {title}\n\n"
            + (f"{goal}\n\n" if goal else "")
            + f"- [ ] {n}.1 Test: a\n- [ ] {n}.2 Do a\n\n"
            for n, (title, goal) in groups.items()
        )
    )


class OnBranch(StubLoop):
    """A stubbed-loop recorder whose commits, head and commit count are the branch's own. Its
    agent writes a file for each tests, implementation and rework call, except for the
    implementation of the groups named in `no_commit_for`, which leaves the tree as it was."""

    def __init__(self, store: UnitStore, *, no_commit_for: str = "", **options: Any) -> None:
        super().__init__(store, **options)
        self.no_commit_for = no_commit_for  # as the prompt names them: "3" or "1, 2, 3"

    def claude(self, prompt: str, **kwargs: Any) -> str:
        answer = super().claude(prompt, **kwargs)
        step = self.events[-1]
        skipped = step == "claude:impl" and group_named(prompt) == self.no_commit_for
        if step in ("claude:tests", "claude:impl", "claude:rework") and not skipped:
            (kwargs["cwd"] / f"work-{len(self.prompts)}.txt").write_text(f"{step}\n")
        return answer

    def commit(self, message: str, *, cwd: Path, base: str = "") -> int:
        made = build_commit(unit_id=UNIT)(message, cwd=cwd, base=base)
        super().commit(message, cwd=cwd, base=base)  # recorded, and the run may die here
        return made

    def head(self, cwd: Path) -> str:
        return git(cwd, "rev-parse", "HEAD").strip()

    def branch_commits(self, cwd: Path, base: str) -> int:
        return branch_commits(cwd, base)

    def overrides(self, tmp_path: Path) -> dict[str, Any]:
        return {**super().overrides(tmp_path), "worktree": lambda u, base: tmp_path / "tree"}


def seeded_branch(tmp_path: Path, subjects: list[str]) -> Path:
    """The unit's branch holding commits with these subjects, as an earlier run left them."""
    repo = branch(tmp_path)
    for index, subject in enumerate(subjects):
        land(repo, subject, {f"seed-{index}.txt": f"{subject}\n"})
    return repo


def messages(repo: Path) -> list[str]:
    """The whole message of each commit on the branch, oldest first."""
    log = git(repo, "log", "--reverse", "--format=%B%x00", f"{BASE}..HEAD")
    return [entry.strip() for entry in log.split("\0") if entry.strip()]


def subjects(repo: Path) -> list[str]:
    return [message.split("\n", 1)[0] for message in messages(repo)]


def built(
    tmp_path: Path,
    *,
    seeded: list[str] | None = None,
    groups: Mapping[str, Groups] | None = None,
    carries: tuple[Member, ...] = (),
    setting: bool = True,
    meanwhile: Callable[[Path], None] | None = None,
    **options: Any,
) -> tuple[OnBranch, RunOutcome, Path]:
    """Build the unit over a branch holding `seeded` subjects. `groups` is each change's tasks,
    the unit's own change first; the unit builds the groups listed under its own change and
    those the members in `carries` name. `meanwhile` acts on the branch before the build starts."""
    activate_with(builders={"per_group_commits": setting})
    tasks = groups or {"add-marker": titled(1, 2, 3)}
    for change, listed in tasks.items():
        write_tasks(tmp_path, change, listed)
    repo = seeded_branch(tmp_path, seeded or [])
    if meanwhile:
        meanwhile(repo)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(groups=tuple(tasks["add-marker"]), joined=carries)])
    recorder = OnBranch(store, **options)
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))
    return recorder, outcome, repo
