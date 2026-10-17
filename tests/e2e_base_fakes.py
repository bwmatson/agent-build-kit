"""A repository with a branch, a pytest-shaped runner and a gate, for the tests of what
e2e-test does with the tests that fail on a unit's branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

from agent_build_kit.config import E2eUnitScope
from agent_build_kit.pipeline.e2e import E2eResult, TestFailure
from agent_build_kit.pipeline.wiring import E2eSession
from agent_build_kit.profiles.python_uv import PROFILE
from tests.factories import git, init_repo, unit

TEST_BODY = "def test_a():\n    assert True\n"
# The command e2e-test runs for a repo with no members.
E2E_COMMAND = PROFILE.e2e_commands(Path("."), marker="local_stack")[0]


def pytest_output(
    failed: dict[str, str] | None = None,
    errored: dict[str, str] | None = None,
    passed: tuple[str, ...] = (),
) -> str:
    """What `pytest -vv -rfE --tb=short` prints for a run: one line per test, then the short
    summary with the first failure line of each failed or errored test."""
    failed, errored = failed or {}, errored or {}
    lines = ["=" * 29 + " test session starts " + "=" * 29]
    lines += [f"{test} FAILED [ 50%]" for test in failed]
    lines += [f"{test} ERROR [ 50%]" for test in errored]
    lines += [f"{test} PASSED [100%]" for test in passed]
    if failed or errored:
        lines.append("=" * 27 + " short test summary info " + "=" * 28)
        lines += [f"FAILED {test} - {line}" for test, line in failed.items()]
        lines += [f"ERROR {test} - {line}" for test, line in errored.items()]
    counts = ", ".join(
        f"{n} {label}"
        for n, label in ((len(failed), "failed"), (len(passed), "passed"), (len(errored), "error"))
        if n
    )
    lines.append("=" * 25 + f" {counts or 'no tests ran'} in 0.03s " + "=" * 25)
    return "\n".join(lines) + "\n"


def failures(*tests: str) -> list[TestFailure]:
    return [TestFailure(test=test, line=f"assert {n} == 0") for n, test in enumerate(tests, 1)]


def result_of(*tests: str) -> E2eResult:
    """A failed e2e-test result that names `tests`."""
    return E2eResult(
        sha="abc1234",
        passed=0,
        failed=len(tests),
        skipped=0,
        duration_seconds=1.0,
        command=" ".join(E2E_COMMAND),
        output="",
        failures=failures(*tests),
    )


def branch(
    tmp_path: Path, changed: dict[str, str], *, base_files: dict[str, str] | None = None
) -> tuple[Path, str]:
    """A repo whose base commit holds `base_files` (and a manifest) and whose one further
    commit writes `changed` over it. Returns the repo, left on that commit, and the base's
    sha."""
    repo = init_repo(tmp_path / "repo")
    (repo / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    for name, text in {"tests/live/test_other.py": TEST_BODY, **(base_files or {})}.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD").strip()
    for name, text in changed.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "unit", "--allow-empty")
    return repo, base


class Runs:
    """A runner that answers the unit's own e2e-test command with `own` and a command run
    anywhere else, the base run, with `base`. Every call is kept with where it ran."""

    def __init__(
        self,
        repo: Path,
        own: str | dict[tuple[str, ...], str],
        base: str = "",
        *,
        raises: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.events = events if events is not None else []
        self.repo, self.own, self.base_output, self.raises = repo, own, base, raises
        self.calls: list[tuple[list[str], Path]] = []
        self.listings: list[list[str]] = []
        self.trees: list[Path] = []
        # What each base run saw checked out, read as it ran: the tree is gone afterwards.
        self.heads: list[str] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        cwd = Path(str(kwargs["cwd"]))
        if "--collect-only" in command:
            # A listing of what a runtime's tag selects: no runtime holds a test here.
            self.listings.append(command)
            return subprocess.CompletedProcess(command, 5, "", "")
        self.calls.append((command, cwd))
        self.events.append("unit" if cwd == self.repo else "base")
        if cwd == self.repo:
            out = self.own[tuple(command)] if isinstance(self.own, dict) else self.own
            return subprocess.CompletedProcess(command, 1, out, "")
        assert cwd.is_dir(), "the base run needs a worktree that exists"
        self.trees.append(cwd)
        self.heads.append(git(cwd, "rev-parse", "HEAD").strip())
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(command, 1, self.base_output, "")

    @property
    def on_unit(self) -> list[list[str]]:
        return [command for command, where in self.calls if where == self.repo]

    @property
    def on_base(self) -> list[list[str]]:
        return [command for command, where in self.calls if where != self.repo]


def session(tmp_path: Path, run: Runs, **kwargs) -> E2eSession:
    """A gate that runs the whole marker: the base run is what a full run reaches."""
    kwargs.setdefault("scope", E2eUnitScope.FULL)
    return E2eSession(
        unit(tier="e2e-test"),
        lock=tmp_path / "t2.lock",
        timeout=5,
        run=run,
        sha=lambda cwd: "abc1234",
        **kwargs,
    )


TIER2_COMMAND = E2E_COMMAND  # abk-shim
