"""`abk policy show`: the recommendation per class, its gaps, false positives and dialect."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import main
from agent_build_kit.runtimes.recommended_policy import (
    DIALECT,
    KNOWN_FALSE_POSITIVES,
    RECOMMENDED,
    UNCOVERED,
)


def test_show_prints_the_recommendation_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ABK_CONFIG", raising=False)
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: pytest.fail("a program was started"))

    code = main(["policy", "show"])
    out = capsys.readouterr().out

    assert code == 0
    for policy in RECOMMENDED:
        assert policy.label in out
        for glob in policy.globs:
            assert glob in out
    for uncovered in UNCOVERED:
        assert uncovered.label in out
        assert uncovered.reason in out
    for command in KNOWN_FALSE_POSITIVES:
        assert command in out
    assert DIALECT in out
    assert "abk doctor" in out
    assert list(empty.iterdir()) == []
