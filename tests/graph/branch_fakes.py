"""The stand-ins a per-group build is driven over a real git branch with: the unit's commits are
made and read with git in the runner's worktree, so a build can start from the commits an earlier
run left, and what a commit says can be read back from the branch."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.commit_order import branch_subjects
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Member
from agent_build_kit.pipeline.wiring import branch_commits, build_commit, build_commit_built
from tests.factories import activate_with, git, stored_unit
from tests.graph.stub_loop_fakes import StubLoop
from tests.graph.test_build_path import build
from tests.graph.test_outside_commits_prompt import branch, land
from tests.graph.test_per_group_build import group_named
from tests.runner_fakes import Killed

UNIT = "add-marker/1"
TRAILER = f"Unit: {UNIT}"
BASE = "origin/main"
Groups = Mapping[int, tuple[str, str]]  # number -> (title, "Done when" sentence or "")
ACCOUNT = "Nothing needed changing. The four tests already pass"


def agent_calls(events: list[str]) -> list[str]:
    """The agent calls among a build's recorded events."""
    return [event for event in events if event.startswith("claude:")]


def titled(*numbers: int) -> Groups:
    """Groups titled `G<number>`, none with a "Done when" sentence."""
    return {number: (f"G{number}", "") for number in numbers}


def write_tasks(
    tmp_path: Path,
    change: str,
    groups: Groups,
    *,
    e2e: Collection[int] = (),
    tests_only: Collection[int] = (),
) -> None:
    """The change's tasks file in the planning repo, where titles and goals are read from.
    The groups in `e2e` are headed `[e2e-test]`, the others `[unit-test]`; those in
    `tests_only` hold nothing but `Test:` tasks."""
    path = tmp_path / "meta" / "openspec" / "changes" / change / "tasks.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            f"## {n}. [app] [{'e2e-test' if n in e2e else 'unit-test'}] {title}\n\n"
            + (f"{goal}\n\n" if goal else "")
            + f"- [ ] {n}.1 Test: a\n"
            + ("" if n in tests_only else f"- [ ] {n}.2 Do a\n")
            + "\n"
            for n, (title, goal) in groups.items()
        )
    )


class OnBranch(StubLoop):
    """A stubbed-loop recorder whose commits, head and commit count are the branch's own. Its
    agent writes a file for each tests, implementation and rework call, except for the
    implementation of the groups named in `no_commit_for` and the tests of those named in
    `no_tests_for`, which leave the tree as it was, and for every call about groups all
    numbered in `silent_groups`. The implementation call of the group named in `kill_in_impl`
    dies once, before it writes. `at_agent` holds the branch's subjects as each tests or
    implementation call found them, with its event. `accounts` is what the implementation
    agent says last, and `tests_accounts` what the tests agent does, by the group it is asked
    about (as the prompt names it)."""

    def __init__(
        self,
        store: UnitStore,
        *,
        no_commit_for: str = "",
        no_tests_for: str = "",
        kill_in_impl: str = "",
        silent_groups: Collection[int] = (),
        accounts: Mapping[str, str] | None = None,
        tests_accounts: Mapping[str, str] | None = None,
        **options: Any,
    ) -> None:
        super().__init__(store, **options)
        self.accounts = accounts or {}
        self.tests_accounts = tests_accounts or {}
        self.no_commit_for = no_commit_for  # as the prompt names them: "3" or "1, 2, 3"
        self.no_tests_for = no_tests_for
        self.kill_in_impl = kill_in_impl  # the run dies, once, in this group's implementation call
        self.at_agent: list[tuple[str, list[str]]] = []
        self.silent_groups = frozenset(str(number) for number in silent_groups)

    def claude(self, prompt: str, **kwargs: Any) -> str:
        answer = super().claude(prompt, **kwargs)
        step = self.events[-1]
        built_group = group_named(prompt) if step in ("claude:tests", "claude:impl") else ""
        skipped = step == "claude:impl" and built_group == self.no_commit_for
        skipped = skipped or (step == "claude:tests" and built_group == self.no_tests_for)
        if step in ("claude:tests", "claude:impl"):
            self.at_agent.append((step, branch_subjects(kwargs["cwd"], BASE)))
        if step == "claude:impl" and built_group == self.kill_in_impl:
            self.kill_in_impl = ""
            raise Killed(step)
        skipped = skipped or (
            bool(built_group) and set(built_group.split(", ")) <= self.silent_groups
        )
        if step in ("claude:tests", "claude:impl", "claude:rework") and not skipped:
            (kwargs["cwd"] / f"work-{len(self.prompts)}.txt").write_text(f"{step}\n")
        if step == "claude:impl" and built_group in self.accounts:
            return self.accounts[built_group]
        if step == "claude:tests" and built_group in self.tests_accounts:
            return self.tests_accounts[built_group]
        return answer

    def commit(self, message: str, *, cwd: Path, base: str = "") -> int:
        made = build_commit(unit_id=UNIT)(message, cwd=cwd, base=base)
        super().commit(message, cwd=cwd, base=base)  # recorded, and the run may die here
        return made

    def commit_built(self, message: str, *, cwd: Path) -> int:
        made = build_commit_built(unit_id=UNIT)(message, cwd=cwd)
        self._after(f"commit_built:{message.split(':')[0]}")  # recorded, and the run may die here
        return made

    def head(self, cwd: Path) -> str:
        return git(cwd, "rev-parse", "HEAD").strip()

    def branch_commits(self, cwd: Path, base: str) -> int:
        return branch_commits(cwd, base)

    def branch_subjects(self, cwd: Path, base: str) -> list[str]:
        return branch_subjects(cwd, base)

    def overrides(self, tmp_path: Path) -> dict[str, Any]:
        return {
            **super().overrides(tmp_path),
            "worktree": lambda u, base: tmp_path / "tree",
            "commit_built": self.commit_built,
        }


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


def prepared(
    tmp_path: Path,
    *,
    seeded: list[str] | None = None,
    groups: Mapping[str, Groups] | None = None,
    carries: tuple[Member, ...] = (),
    setting: bool = True,
    meanwhile: Callable[[Path], None] | None = None,
    guidance: str = "",
    e2e: Collection[int] = (),
    tests_only: Collection[int] = (),
    **options: Any,
) -> tuple[OnBranch, Path]:
    """The recorder and the branch for building the unit over a branch holding `seeded`
    subjects. `groups` is each change's tasks, the unit's own change first; the unit builds
    the groups listed under its own change and those the members in `carries` name. `e2e` and
    `tests_only` are the numbers of its own change's groups headed `[e2e-test]` and holding only
    tests. `meanwhile` acts on the branch before the build starts, and `guidance` is a person's
    note saved on the unit before it does."""
    activate_with(builders={"stubbed_tdd_commits": setting})
    tasks = groups or {"add-marker": titled(1, 2, 3)}
    for change, listed in tasks.items():
        own = change == "add-marker"
        write_tasks(
            tmp_path,
            change,
            listed,
            e2e=e2e if own else (),
            tests_only=tests_only if own else (),
        )
    repo = seeded_branch(tmp_path, seeded or [])
    if meanwhile:
        meanwhile(repo)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(groups=tuple(tasks["add-marker"]), joined=carries)])
    if guidance:
        store.set_guidance(UNIT, guidance)
    return OnBranch(store, **options), repo


def built(tmp_path: Path, **kwargs: Any) -> tuple[OnBranch, RunOutcome, Path]:
    """Build the unit over the branch `prepared` makes."""
    recorder, repo = prepared(tmp_path, **kwargs)
    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))
    return recorder, outcome, repo


def built_after_a_pair(tmp_path: Path, **options: Any) -> tuple[OnBranch, RunOutcome, Path]:
    """Groups 3 and 4 built, group 3 by a pair of its agents' commits and group 4 by agents who
    commit nothing, the implementation agent saying `ACCOUNT` last."""
    return built(
        tmp_path,
        groups={"add-marker": titled(3, 4)},
        silent_groups=(4,),
        **{"accounts": {"4": ACCOUNT}, **options},
    )


def files_in(repo: Path, rev: str) -> list[str]:
    """The files a commit changes."""
    return git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", rev).split()


def recorded_pair(repo: Path) -> None:
    """Assert the branch ends with an empty, marked pair for group 4 after group 3's real one."""
    assert subjects(repo) == ["test: G3", "feat: G3", "test: G4", "feat: G4"]
    for rev, marked in (("HEAD~3", False), ("HEAD~2", False), ("HEAD~1", True), ("HEAD", True)):
        message = git(repo, "log", "-1", "--format=%B", rev)
        assert TRAILER in message
        assert ("Already-built: yes" in message) is marked, message
        assert (files_in(repo, rev) == []) is marked, rev
