"""`abk config` and `abk doctor` refuse a file that sets the removed key, naming the setting that
replaces it and the command that moves it."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import run_doctor
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

OLD = "version: 1\nglobal_limits:\n  max_unit_lines: 600\n"


def test_abk_config_fails_naming_the_replacement_and_the_migration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(OLD)

    code = main(["--config", str(path), "config"])

    assert code != 0
    err = capsys.readouterr().err
    assert "review.ceilings.full" in err
    assert "abk config --migrate" in err


def test_the_effective_ceilings_are_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text("version: 1\nreview:\n  ceilings:\n    full: 600\n")

    main(["--config", str(path), "config"])

    out = capsys.readouterr().out
    assert yaml.safe_load(out)["review"]["ceilings"] == {"auto": 5000, "light": 2000, "full": 600}


def test_doctor_fails_the_config_check_naming_the_replacement_and_the_migration(
    tmp_path: Path,
) -> None:
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(OLD)

    checks = run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)

    config = next(check for check in checks if check.name == "config")
    assert config.status == "FAIL"
    assert "review.ceilings.full" in config.detail + config.fix
    assert "abk config --migrate" in config.detail + config.fix
