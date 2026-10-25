"""`abk doctor`'s sandbox probe starts `abk install-config` from inside a confined step, past the
loading of the installation, and fails naming the path when the command cannot start (spec:
sandbox-abk-exec)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.cli import doctor
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.sandboxes import SandboxPolicy
from agent_build_kit.sandboxes.policy import own_installation
from tests.cli.sandbox_cli_support import NAME, CountingBackend, switch_on
from tests.cli.test_doctor import Answers, workspace  # noqa: F401 — fixture
from tests.factories import which_all
from tests.sandboxes.policy_support import reads

REFUSED = "abk install-config: refused: .abk/proposed/none.yaml is not a regular file"


class Confining(CountingBackend):
    """Stands in for the confined command. `config` is the file the command must read to start:
    when the policy does not list it the command fails as a denied open does, naming it; when it
    does, the command gets as far as `abk install-config` refusing its staged file. `denied`
    makes it fail at the exec instead."""

    def __init__(self, config: Path, denied: str = "") -> None:
        super().__init__()
        self.config = config
        self.denied = denied

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        super().command(policy, argv)
        if "install-config" not in " ".join(argv):
            return ["true"]
        if self.denied:
            return ["sh", "-c", f"echo 'sh: 1: {self.denied}: Permission denied' >&2; exit 126"]
        if not reads(policy, self.config):
            return [
                "sh",
                "-c",
                f"echo \"PermissionError: [Errno 13] Permission denied: '{self.config}'\" >&2; "
                "exit 1",
            ]
        return ["sh", "-c", f"echo '{REFUSED}' >&2; exit 1"]


@pytest.fixture
def abk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    entry = tmp_path / "tools" / "bin" / "abk"
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: str(entry))
    return entry


def backend(config: Path, denied: str = "") -> Iterator[Confining]:
    with sandboxes.isolated():
        found = Confining(config, denied)
        sandboxes.register(found)
        yield found


@pytest.fixture
def allowing(workspace: Path) -> Iterator[Confining]:  # noqa: F811 — fixture
    yield from backend(workspace / "abk.yaml")


@pytest.fixture
def refusing_exec(workspace: Path, abk: Path) -> Iterator[Confining]:  # noqa: F811 — fixture
    yield from backend(workspace / "abk.yaml", denied=str(abk))


def sandbox_checks(config: Path) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [c for c in checks if "sandbox" in c.name]


def test_the_probe_starts_abk_install_config_with_the_reads_a_step_gets(
    workspace: Path,  # noqa: F811 — fixture
    allowing: Confining,
    abk: Path,
) -> None:
    switch_on(workspace / "abk.yaml", backend=NAME)

    found = sandbox_checks(workspace / "abk.yaml")

    carrying = [
        policy for policy, argv in allowing.asked if f"{abk} install-config" in " ".join(argv)
    ]
    assert carrying, allowing.asked
    for path in own_installation():
        assert reads(carrying[0], path), path
    assert reads(carrying[0], workspace / "abk.yaml")
    assert not carrying[0].write
    assert [c.status for c in found] == ["ok"], found


def test_a_policy_that_leaves_out_the_config_read_fails_the_check_naming_the_file(
    workspace: Path,  # noqa: F811 — fixture
    allowing: Confining,
    abk: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch_on(workspace / "abk.yaml", backend=NAME)
    monkeypatch.setattr(doctor, "builtin_reads", lambda inst, changes=(): own_installation())

    found = sandbox_checks(workspace / "abk.yaml")

    failed = [c for c in found if c.status == "FAIL"]
    assert failed, found
    assert str(workspace / "abk.yaml") in failed[0].detail


def test_a_command_that_cannot_start_fails_the_check_naming_the_path(
    workspace: Path,  # noqa: F811 — fixture
    refusing_exec: Confining,
    abk: Path,
) -> None:
    switch_on(workspace / "abk.yaml", backend=NAME)

    found = sandbox_checks(workspace / "abk.yaml")

    failed = [c for c in found if c.status == "FAIL"]
    assert failed, found
    assert str(abk) in failed[0].detail


def test_an_abk_that_is_not_on_the_path_is_not_a_sandbox_failure(
    workspace: Path,  # noqa: F811 — fixture
    allowing: Confining,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    switch_on(workspace / "abk.yaml", backend=NAME)
    monkeypatch.setattr(shutil, "which", lambda name, *a, **k: None)

    found = sandbox_checks(workspace / "abk.yaml")

    assert [c.status for c in found] == ["ok"], found
    assert not [argv for _, argv in allowing.asked if "install-config" in " ".join(argv)]
