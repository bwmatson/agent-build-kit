"""The home-path scan reads the checkout's configuration a fixed number of times, however many
files it scans.

The scan over the whole repository timed out under parallel load because it parsed `abk.yaml`
again for every file it looked at. The cost is counted here, not timed: a test never waits on
the clock to see it.
"""

from pathlib import Path

import pytest
import yaml

from tests.installation_leaks import home_path_leaks


def _checkout(root: Path, files: int) -> None:
    (root / "abk.yaml").write_text("planning:\n  specs_dir: openspec/specs\n")
    (root / "src").mkdir()
    for number in range(files):
        (root / "src" / f"module_{number}.py").write_text("x = 1\n")


def _config_parses(root: Path, monkeypatch: pytest.MonkeyPatch) -> int:
    parses = 0
    real = yaml.safe_load

    def counting(stream):
        nonlocal parses
        parses += 1
        return real(stream)

    monkeypatch.setattr(yaml, "safe_load", counting)
    assert home_path_leaks(root) == []
    return parses


def test_the_configuration_is_parsed_no_more_often_for_more_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    few, many = tmp_path / "few", tmp_path / "many"
    few.mkdir()
    many.mkdir()
    _checkout(few, 2)
    _checkout(many, 40)

    assert _config_parses(many, monkeypatch) == _config_parses(few, monkeypatch)


def test_the_configuration_is_parsed_once_for_a_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _checkout(tmp_path, 10)

    assert _config_parses(tmp_path, monkeypatch) <= 1
