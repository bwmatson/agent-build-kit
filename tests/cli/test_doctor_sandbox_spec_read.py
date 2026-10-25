"""`abk doctor`'s sandbox probe reads a file under the specs folder from inside a confined step and
fails naming the path when the read is refused (spec: sandbox-spec-reads)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.sandboxes import SandboxPolicy, held
from tests.cli.sandbox_cli_support import NAME, CountingBackend, switch_on
from tests.cli.test_doctor import Answers, workspace  # noqa: F401 — fixture
from tests.factories import which_all


class Confining(CountingBackend):
    """Runs the confined command itself; `refuse` makes the read it carries fail as a sandbox's
    refusal would, with the exit status of a denied open."""

    def __init__(self, *, refuse: bool) -> None:
        super().__init__()
        self.refuse = refuse

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        super().command(policy, argv)
        if self.refuse:
            return ["sh", "-c", "echo 'Permission denied' >&2; exit 13"]
        return list(argv)


@pytest.fixture
def allowing() -> Iterator[Confining]:
    with sandboxes.isolated():
        found = Confining(refuse=False)
        sandboxes.register(found)
        yield found


@pytest.fixture
def refusing() -> Iterator[Confining]:
    with sandboxes.isolated():
        found = Confining(refuse=True)
        sandboxes.register(found)
        yield found


def sandbox_checks(config: Path) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [c for c in checks if "sandbox" in c.name]


def spec_file(workspace: Path) -> Path:  # noqa: F811 — fixture
    file = workspace / "openspec" / "changes" / "feature" / "tasks.md"
    file.parent.mkdir(parents=True)
    file.write_text("## 1. [app] [unit-test] Work\n")
    return file


def test_the_probe_reads_a_file_under_the_specs_folder_from_a_confined_step(
    workspace: Path,  # noqa: F811 — fixture
    allowing: Confining,
) -> None:
    file = spec_file(workspace)
    switch_on(workspace / "abk.yaml", backend=NAME)

    sandbox_checks(workspace / "abk.yaml")

    carrying = [
        (policy, argv)
        for policy, argv in allowing.asked
        if any(str(file) in word or file.name in word for word in argv)
    ]
    assert carrying, allowing.asked
    policy, _ = carrying[0]
    assert any(file.resolve().is_relative_to(folder) for folder in policy.read)


def test_a_refused_read_fails_the_check_naming_the_path(
    workspace: Path,  # noqa: F811 — fixture
    refusing: Confining,
) -> None:
    file = spec_file(workspace)
    switch_on(workspace / "abk.yaml", backend=NAME)

    found = sandbox_checks(workspace / "abk.yaml")

    failed = [c for c in found if c.status == "FAIL"]
    assert failed, found
    assert str(file) in failed[0].detail


def test_a_read_that_never_finishes_fails_the_check_naming_the_path(
    workspace: Path,  # noqa: F811 — fixture
    refusing: Confining,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file = spec_file(workspace)
    switch_on(workspace / "abk.yaml", backend=NAME)
    monkeypatch.setattr(held, "TIMEOUT", 0.2)
    monkeypatch.setattr(refusing, "command", lambda policy, argv: ["sleep", "60"])

    found = sandbox_checks(workspace / "abk.yaml")

    failed = [c for c in found if c.status == "FAIL"]
    assert failed, found
    assert str(file) in failed[0].detail
