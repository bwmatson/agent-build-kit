"""`abk config` prints both limit blocks, and `--path` runs on a file that will not load."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main

MOVED_TEXT = "version: 1\nglobal_limits:\n  max_units_in_progress: 5\n"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return path


def test_both_blocks_are_printed_with_their_defaults(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "version: 1\n")

    code = main(["--config", str(path), "config"])

    assert code == 0
    shown = yaml.safe_load(capsys.readouterr().out)
    assert shown["project_limits"] == {
        "max_units_in_progress": 5,
        "max_concurrent_stacks": 4,
        "max_concurrent_restacks": 2,
        "emergency_extra": 1,
    }
    assert "max_review_rounds" in shown["global_limits"]
    assert "max_units_in_progress" not in shown["global_limits"]


def test_show_exits_2_with_the_load_error_and_the_pointer_while_path_still_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, MOVED_TEXT)

    shown = main(["--config", str(path), "config"])
    err = capsys.readouterr().err
    located = main(["--config", str(path), "config", "--path"])

    assert shown == 2
    assert "global_limits.max_units_in_progress" in err
    assert "project_limits.max_units_in_progress" in err
    assert "abk config --migrate" in err
    assert located == 0
    assert capsys.readouterr().out.strip() == str(path)


def test_path_without_any_abk_yaml_exits_2_naming_what_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ABK_CONFIG", raising=False)

    code = main(["config", "--path"])

    assert code == 2
    assert "no abk.yaml found" in capsys.readouterr().err
