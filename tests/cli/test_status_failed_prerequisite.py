"""`abk status` names a failed unit that others wait on, and says to requeue it."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import FAILED
from tests.conftest import status_lines
from tests.factories import new_unit


def test_status_lists_a_failed_unit_with_the_number_waiting_and_a_requeue_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            new_unit("base/1", state=FAILED),
            new_unit("one/1", depends_on=("base/1",)),
            new_unit("two/1", depends_on=("one/1",)),
            new_unit("alone/1", state=FAILED),
        ],
    )

    named = next(line for line in lines if "base/1" in line and "waiting" in line)
    assert "2 units waiting" in named
    assert "requeue" in named
    assert not any("alone/1" in line and "requeue" in line for line in lines)
