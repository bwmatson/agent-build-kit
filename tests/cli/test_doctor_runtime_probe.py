"""`abk doctor` reports from the probe `abk init` uses: the other runtimes this machine can
run, a selected entry that is only documented, and an entry recorded as unchecked."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import run_doctor
from tests.cli.init_choice_fakes import Offering
from tests.cli.test_doctor import (  # noqa: F401 — fixture
    Answers,
    select_runtime,
    workspace,
)
from tests.runtimes.selectable import SelectableRuntime, select, spelling_report


def without(*programs: str) -> Callable[[str], str | None]:
    """A path holding every program but `programs`."""
    return lambda name: None if name in programs else f"/usr/bin/{name}"


def test_other_usable_runtimes_are_reported_as_information(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("alpha", "beta", "gamma"):
        select(monkeypatch, Offering(name, events=[]))
    select_runtime(workspace, "alpha", "    command: [alpha-bin, acp]\n")

    checks = run_doctor(workspace / "abk.yaml", run=Answers(), which=without("gamma-bin"))

    others = [c for c in checks if c.status == "info" and "other usable runtimes" in c.detail]
    assert len(others) == 1
    assert "beta" in others[0].detail
    assert "gamma" not in others[0].detail
    assert "alpha" not in others[0].detail


def test_a_selected_entry_that_is_only_documented_is_a_warning(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    select(monkeypatch, Offering("alpha", events=[]))
    select_runtime(workspace, "alpha", "    command: [alpha-bin, acp]\n")

    checks = run_doctor(workspace / "abk.yaml", run=Answers(), which=without())

    documented = [c for c in checks if c.status == "warn" and "documented only" in c.detail]
    assert len(documented) == 1


def test_an_entry_recorded_as_unchecked_warns_on_every_run_and_sends_no_prompt(
    workspace: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = select(monkeypatch, SelectableRuntime("declined", reports=(spelling_report(),)))
    select_runtime(workspace, "declined", "    policy: unchecked\n")

    for _ in range(2):
        checks = run_doctor(workspace / "abk.yaml", run=Answers(), which=without())
        warned = [c for c in checks if c.status == "warn" and "unchecked" in c.detail]
        assert len(warned) == 1

    assert runtime.checked == []
