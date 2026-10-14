"""`abk config` says on the error stream that `limits` is deprecated, and still prints."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main


def run_config(
    tmp_path: Path, text: str, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    code = main(["--config", str(path), "config"])
    seen = capsys.readouterr()
    return code, seen.out, seen.err


def test_the_old_key_prints_the_config_and_says_how_to_move(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_config(tmp_path, "version: 1\nlimits:\n  max_review_rounds: 5\n", capsys)

    assert code == 0
    assert yaml.safe_load(out)["global_limits"]["max_review_rounds"] == 5
    assert "deprecated" in err
    assert "`limits`" in err
    assert "`global_limits`" in err
    assert "abk config --migrate" in err


def test_the_new_key_says_nothing_of_the_kind(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_config(
        tmp_path, "version: 1\nglobal_limits:\n  max_review_rounds: 5\n", capsys
    )

    assert code == 0
    assert yaml.safe_load(out)["global_limits"]["max_review_rounds"] == 5
    assert "deprecated" not in err
    assert "--migrate" not in err
