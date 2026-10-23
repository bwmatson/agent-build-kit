"""`abk doctor` and `abk init` say what to do on a Mac when the Seatbelt probe fails. The platform
is switched to macOS and `sandbox-exec` is a stand-in on PATH, so no Mac is needed."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.sandbox_cli_support import switch_on
from tests.cli.test_doctor import Answers, workspace  # noqa: F401 — fixture
from tests.cli.test_init import app, init_args, stubs  # noqa: F401 — fixtures
from tests.cli.test_init_sandbox import rerun
from tests.factories import which_all
from tests.sandboxes.seatbelt_support import as_macos, fake_sandbox_exec, no_sandbox_exec


def sandbox_checks(config: Path) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [c for c in checks if "sandbox" in c.name]


def test_doctor_on_a_mac_without_sandbox_exec_fails_saying_what_to_do(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,  # noqa: F811 — fixture
) -> None:
    as_macos(monkeypatch)
    no_sandbox_exec(monkeypatch)
    switch_on(workspace / "abk.yaml", backend="seatbelt")

    found = sandbox_checks(workspace / "abk.yaml")

    assert [c.status for c in found] == ["FAIL"]
    assert "seatbelt" in found[0].detail
    assert "sandbox-exec" in found[0].detail
    assert "sandbox-exec" in found[0].fix
    assert "required: none" in found[0].fix


def test_doctor_on_a_mac_where_a_denied_write_goes_through_fails_naming_the_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,  # noqa: F811 — fixture
) -> None:
    as_macos(monkeypatch)
    fake_sandbox_exec(tmp_path, monkeypatch, confines=False)
    switch_on(workspace / "abk.yaml", backend="seatbelt")

    found = sandbox_checks(workspace / "abk.yaml")

    assert [c.status for c in found] == ["FAIL"]
    assert "write" in found[0].detail
    assert "required: none" in found[0].fix


def test_doctor_names_the_platform_when_seatbelt_is_asked_for_off_a_mac(
    monkeypatch: pytest.MonkeyPatch,
    workspace: Path,  # noqa: F811 — fixture
) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    switch_on(workspace / "abk.yaml", backend="seatbelt")

    found = sandbox_checks(workspace / "abk.yaml")

    assert [c.status for c in found] == ["FAIL"]
    assert "linux" in found[0].detail
    assert "macOS" in found[0].fix


def test_init_on_a_mac_without_sandbox_exec_prints_the_cause_and_the_fix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app: Path,  # noqa: F811 — fixture
    capsys: pytest.CaptureFixture[str],
) -> None:
    as_macos(monkeypatch)
    no_sandbox_exec(monkeypatch)

    lines = rerun(tmp_path, app, capsys, on=True, backend="seatbelt")

    text = "\n".join(lines)
    assert "sandbox-exec" in text
    assert "required: none" in text
