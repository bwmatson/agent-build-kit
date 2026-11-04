"""`abk status` shows each repo's worker mode: its own `workers.mode`, else the top-level one
(spec: worker-kinds)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import status_lines


def mode_line(lines: list[str], repo: str) -> str:
    found = [line for line in lines if "workers" in line.lower() and repo in line]
    assert len(found) == 1, f"one worker-mode line for {repo}: {lines}"
    return found[0]


def test_status_names_each_repos_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repos = {
        "app": {
            "path": str(tmp_path / "checkouts" / "app"),
            "slug": "example/app",
            "workers": {"mode": "processes"},
        },
        "platform": {"path": str(tmp_path / "checkouts" / "platform"), "slug": "example/platform"},
    }

    lines = status_lines(tmp_path, monkeypatch, capsys, repos=repos)

    assert "processes" in mode_line(lines, "app")
    assert "threads" in mode_line(lines, "platform")
