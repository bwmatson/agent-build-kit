"""`abk policy check` and `abk status` show a runtime's `sandbox_coverage` beside its
`policy_coverage`."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.runtimes.base import PolicyReport
from agent_build_kit.sandboxes import Coverage
from agent_build_kit.settings import reload
from tests.cli.policy_step_fakes import configured
from tests.cli.test_init import app, stubs  # noqa: F401 — fixtures
from tests.conftest import make_installation
from tests.runtimes.selectable import SelectableRuntime, select


def beside(lines: list[str], coverage: Coverage) -> bool:
    return any(
        "policy_coverage: all_calls" in line and f"sandbox_coverage: {coverage.value}" in line
        for line in lines
    )


def test_every_built_in_runtime_has_a_sandbox_coverage() -> None:
    for name in runtimes.names():
        assert runtimes.get(name).sandbox_coverage in set(Coverage), name


def test_no_built_in_runtime_claims_confinement_nothing_provides_yet() -> None:
    assert runtimes.get("claude_code").sandbox_coverage is Coverage.NONE
    assert runtimes.get("acp").sandbox_coverage is Coverage.NONE


@pytest.mark.parametrize("coverage", list(Coverage))
def test_policy_check_prints_the_two_coverages_on_one_line(
    tmp_path: Path,
    app: Path,  # noqa: F811 — fixture
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    coverage: Coverage,
) -> None:
    runtime = SelectableRuntime(
        "covered", sandbox_coverage=coverage, reports=(PolicyReport(ok=True),)
    )
    planning = configured(tmp_path, app, monkeypatch, runtime)
    capsys.readouterr()

    code = main(["--config", str(planning / "abk.yaml"), "policy", "check"])

    shown = capsys.readouterr()
    assert code == 0
    assert beside((shown.out + shown.err).splitlines(), coverage)


@pytest.fixture
def machine_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ABK_RUNTIME", "covered")
    reload(None)
    yield
    monkeypatch.delenv("ABK_RUNTIME", raising=False)
    reload(None)


def test_status_prints_the_two_coverages_on_one_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    machine_runtime: None,
) -> None:
    select(monkeypatch, SelectableRuntime("covered", sandbox_coverage=Coverage.FILES))
    capsys.readouterr()

    cli.cmd_status(argparse.Namespace(), make_installation(tmp_path))

    shown = capsys.readouterr()
    assert beside((shown.out + shown.err).splitlines(), Coverage.FILES)
