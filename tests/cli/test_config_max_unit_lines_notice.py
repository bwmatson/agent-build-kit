"""`abk config` says `global_limits.max_unit_lines` is deprecated for `review.ceilings.full`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main


def run_config(root: Path, text: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "abk.yaml"
    path.write_text(text)
    code = main(["--config", str(path), "config"])
    seen = capsys.readouterr()
    return code, seen.out, seen.err


def test_the_key_is_noticed_once_naming_the_key_and_its_replacement(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run_config(
        tmp_path, "version: 1\nglobal_limits:\n  max_unit_lines: 600\n", capsys
    )

    assert code == 0
    assert err.count("global_limits.max_unit_lines") == 1
    assert "review.ceilings.full" in err
    assert "deprecated" in err
    assert "abk config --migrate" in err


def test_nothing_is_said_when_the_key_is_not_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, _, noisy = run_config(
        tmp_path / "set", "version: 1\nglobal_limits:\n  max_unit_lines: 600\n", capsys
    )
    code, _, quiet = run_config(
        tmp_path / "quiet", "version: 1\nreview:\n  ceilings:\n    full: 600\n", capsys
    )

    assert "max_unit_lines" in noisy
    assert code == 0
    assert "max_unit_lines" not in quiet


def test_the_effective_ceilings_are_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _, out, _ = run_config(tmp_path, "version: 1\nglobal_limits:\n  max_unit_lines: 600\n", capsys)

    assert yaml.safe_load(out)["review"]["ceilings"] == {"auto": 5000, "light": 2000, "full": 600}
