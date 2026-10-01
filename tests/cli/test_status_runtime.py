"""`abk status` is what an operator runs to find out what is wrong, so a runtime
that is selected but not installed is something it reports, not dies on."""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.settings import reload
from tests.conftest import make_installation


@pytest.fixture
def machine_runtime(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ABK_RUNTIME", "not-installed")
    reload(None)
    yield
    monkeypatch.delenv("ABK_RUNTIME", raising=False)
    reload(None)


def test_status_reports_a_runtime_that_is_not_available_and_carries_on(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], machine_runtime: None
) -> None:
    code = cli.cmd_status(argparse.Namespace(), make_installation(tmp_path))

    assert code == 0
    output = capsys.readouterr()
    assert "runtime not-installed is not available" in output.out + output.err
    assert "no units planned" in output.out + output.err
