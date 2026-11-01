"""`abk doctor` runs the sandbox backend's probe and reports what it found."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.sandbox_cli_support import CountingBackend, switch_on
from tests.cli.sandbox_cli_support import broken_stand_in as broken_stand_in  # noqa: F401
from tests.cli.sandbox_cli_support import stand_in as stand_in  # noqa: F401
from tests.cli.test_doctor import Answers, workspace  # noqa: F401 — fixture
from tests.factories import which_all

pytestmark = pytest.mark.sandbox_probe


def sandbox_checks(config: Path) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [c for c in checks if "sandbox" in c.name]


def test_a_backend_that_works_is_reported_ok_by_running_its_probe(
    workspace: Path,  # noqa: F811 — fixture
    stand_in: CountingBackend,  # noqa: F811 — fixture
) -> None:
    switch_on(workspace / "abk.yaml")

    found = sandbox_checks(workspace / "abk.yaml")

    assert [c.status for c in found] == ["ok"]
    assert stand_in.name in found[0].detail
    assert stand_in.probes >= 1


def test_a_backend_that_does_not_work_fails_naming_the_cause_and_the_fix(
    workspace: Path,  # noqa: F811 — fixture
    broken_stand_in: CountingBackend,  # noqa: F811 — fixture
) -> None:
    switch_on(workspace / "abk.yaml")

    found = sandbox_checks(workspace / "abk.yaml")

    assert [c.status for c in found] == ["FAIL"]
    assert "stand-in off" in found[0].detail
    assert "turn on" in found[0].fix
    assert broken_stand_in.probes >= 1


def test_a_sandbox_that_is_off_is_one_line_and_the_probe_is_not_run(
    workspace: Path,  # noqa: F811 — fixture
    stand_in: CountingBackend,  # noqa: F811 — fixture
) -> None:
    # Named here because the default is on: this test is about `enabled: false`.
    with (workspace / "abk.yaml").open("a") as handle:
        handle.write("sandbox:\n  enabled: false\n")

    found = sandbox_checks(workspace / "abk.yaml")

    assert len(found) == 1
    assert found[0].status in ("ok", "info")
    assert "off" in found[0].detail
    assert stand_in.probes == 0
