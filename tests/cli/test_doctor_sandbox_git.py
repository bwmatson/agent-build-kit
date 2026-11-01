"""`abk doctor`'s sandbox probe runs `git status` and `git log -1` in a scratch worktree from a
confined step, and fails naming the path git could not read (spec: sandbox-git-reads)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.sandboxes import SandboxPolicy
from tests.cli.sandbox_cli_support import NAME, CountingBackend, switch_on
from tests.cli.test_doctor import Answers, workspace  # noqa: F401 — fixture
from tests.factories import which_all

pytestmark = pytest.mark.sandbox_probe

UNREADABLE = "/scratch/worktree/.git/config"


class Running(CountingBackend):
    """Answers every confined command with one that succeeds, or, when `refuse` is set, with the
    failure `git` prints for a refused read."""

    def __init__(self, *, refuse: bool) -> None:
        super().__init__()
        self.refuse = refuse

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        super().command(policy, argv)
        if self.refuse:
            message = f"fatal: unable to access '{UNREADABLE}': Permission denied"
            return ["sh", "-c", f'echo "{message}" >&2; exit 128']
        return ["true"]


def backend(*, refuse: bool) -> Iterator[Running]:
    with sandboxes.isolated():
        found = Running(refuse=refuse)
        sandboxes.register(found)
        yield found


@pytest.fixture
def allowing() -> Iterator[Running]:
    yield from backend(refuse=False)


@pytest.fixture
def refusing() -> Iterator[Running]:
    yield from backend(refuse=True)


def sandbox_checks(config: Path) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [c for c in checks if "sandbox" in c.name]


def test_the_probe_runs_both_git_commands_from_a_confined_step(
    workspace: Path,  # noqa: F811 — fixture
    allowing: Running,
) -> None:
    switch_on(workspace / "abk.yaml", backend=NAME)

    found = sandbox_checks(workspace / "abk.yaml")

    scripts = [argv[-1] for _, argv in allowing.asked if argv and argv[0] == "sh"]
    carrying = [s for s in scripts if "git status" in s and "git log -1" in s]
    assert carrying, allowing.asked
    assert [c.status for c in found] == ["ok"]


def test_a_personal_configuration_that_stops_a_commit_does_not_stop_the_doctor(
    workspace: Path,  # noqa: F811 — fixture
    allowing: Running,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    home = tmp_path / "personal-home"
    home.mkdir()
    (home / ".gitconfig").write_text("[commit]\n\tgpgsign = true\n[gpg]\n\tprogram = false\n")
    monkeypatch.setenv("HOME", str(home))
    switch_on(workspace / "abk.yaml", backend=NAME)

    found = sandbox_checks(workspace / "abk.yaml")

    assert [c.status for c in found] == ["ok"]


def test_a_refused_read_fails_the_check_naming_the_path(
    workspace: Path,  # noqa: F811 — fixture
    refusing: Running,
) -> None:
    switch_on(workspace / "abk.yaml", backend=NAME)

    found = sandbox_checks(workspace / "abk.yaml")

    failed = [c for c in found if c.status == "FAIL"]
    assert failed, found
    assert UNREADABLE in failed[0].detail
