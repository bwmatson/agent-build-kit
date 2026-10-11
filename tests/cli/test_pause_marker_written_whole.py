"""A test's own pause marker never reads as torn.

The marker is read without a lock and an unreadable one reads as "not paused",
so a marker written in place can release a rate-limit pause early while a pass
reads it between truncation and write."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline import pause
from tests.factories import write_rate_limit_marker


def test_the_marker_is_never_written_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "paused.json"
    in_place: list[Path] = []
    real_write_text = Path.write_text

    def recording(self: Path, *args, **kwargs):
        if self == marker:
            in_place.append(self)
        return real_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", recording)

    write_rate_limit_marker(marker, datetime.now(UTC) + timedelta(hours=1))

    assert in_place == [], "a reader between truncation and write sees a torn marker"


def test_the_marker_is_a_complete_rate_limit_pause_ending_at_the_given_moment(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "paused.json"
    until = datetime.now(UTC) + timedelta(hours=1)

    write_rate_limit_marker(marker, until)

    held = pause.is_paused(marker)
    assert held is not None
    assert held.kind == "rate_limit"
    assert held.until == until
    assert json.loads(marker.read_text())["until"] == until.isoformat()


def test_no_partial_file_is_left_beside_the_marker(tmp_path: Path) -> None:
    marker = tmp_path / "paused.json"

    write_rate_limit_marker(marker, datetime.now(UTC) + timedelta(hours=1))

    assert [p.name for p in tmp_path.iterdir()] == ["paused.json"]
