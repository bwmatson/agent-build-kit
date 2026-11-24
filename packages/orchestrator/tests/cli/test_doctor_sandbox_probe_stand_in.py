"""A doctor run in the suite starts no sandbox probe unless its test is marked `sandbox_probe`."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.sandboxes import held
from tests.cli.in_repo_doctor import checks_of, in_repo, named


class Probes:
    """Stands in for the probes `sandbox_check` starts and counts the git probe's runs."""

    def __init__(self) -> None:
        self.git_runs = 0

    def run_replacing(self, *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.git_runs += 1
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")


@pytest.fixture
def probes(monkeypatch: pytest.MonkeyPatch) -> Probes:
    seen = Probes()
    monkeypatch.setattr(held, "run_replacing", seen.run_replacing)
    # The backend is the passing stand-in that `stand_in_sandbox_backend` registers under tests/cli,
    # so the git probe is reached on any host. The other two probes read the specs folder and
    # start `abk`; this test counts only the git one.
    monkeypatch.setattr("agent_build_kit.cli.doctor._spec_read_failure", lambda *a, **k: "")
    monkeypatch.setattr("agent_build_kit.cli.doctor._abk_exec_failure", lambda *a, **k: "")
    return seen


def test_an_unmarked_doctor_run_gets_the_stand_in_and_starts_no_probe(
    tmp_path: Path, probes: Probes
) -> None:
    [sandbox] = named(checks_of(in_repo(tmp_path / "app")), "sandbox")

    assert sandbox.status == "info"
    assert "sandbox_probe" in sandbox.detail + sandbox.fix
    assert probes.git_runs == 0


@pytest.mark.sandbox_probe
def test_a_marked_doctor_run_gets_the_real_check(tmp_path: Path, probes: Probes) -> None:
    [sandbox] = named(checks_of(in_repo(tmp_path / "app")), "sandbox")

    assert "sandbox_probe" not in sandbox.detail + sandbox.fix
    assert probes.git_runs == 1
