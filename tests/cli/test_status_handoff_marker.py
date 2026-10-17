"""`abk status` marks a handoff unit in the ready queue, after its reason."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import ready_queue, status_lines
from tests.factories import stored_unit


def test_status_marks_a_handoff_unit_and_only_while_a_unit_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [
        stored_unit("urgent/1", change="urgent", priority=1),
        stored_unit("prerequisite/1", change="prerequisite", priority=2),
    ]
    blocked = stored_unit(
        "blocked/1", change="blocked", branch="spec/blocked/1", depends_on=("prerequisite/1",)
    )
    (tmp_path / "blocked").mkdir()
    (tmp_path / "plain").mkdir()

    with_blocked = ready_queue(
        status_lines(tmp_path / "blocked", monkeypatch, capsys, [*units, blocked])
    )
    without = ready_queue(status_lines(tmp_path / "plain", monkeypatch, capsys, units))

    assert with_blocked == [
        "1. urgent/1 (app) — priority 1",
        "2. prerequisite/1 (app) — priority 2 (handoff)",
    ]
    assert without
    assert not any("(handoff)" in line for line in without)
