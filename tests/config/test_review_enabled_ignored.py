"""`review.enabled` is ignored with one notice (spec: review-by-tier-is-always-on)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import yaml

from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import ReviewConfig, deprecations, load
from agent_build_kit.init.scaffold import REVIEW_BLOCK
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

KEY = "review.enabled"
SET = "review:\n  enabled: false\n"
UNSET = "review:\n  brief: true\n"


def write(root: Path, body: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "abk.yaml"
    path.write_text(
        "version: 1\nrepos:\n  app:\n    path: /work/app\n    slug: example/app\n" + body
    )
    return path


def doctor(tmp_path: Path, body: str) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(f"version: 1\n{body}")
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


@pytest.mark.parametrize("value", ["false", "true"])
def test_a_file_that_sets_the_key_loads_and_the_model_has_no_such_field(
    tmp_path: Path, value: str
) -> None:
    config = load(write(tmp_path, f"review:\n  enabled: {value}\n"))

    assert "enabled" not in ReviewConfig.model_fields
    assert "enabled" not in config.review.model_dump()


def test_the_loader_gives_one_notice_naming_the_key(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = write(tmp_path, SET)

    with caplog.at_level(logging.WARNING):
        load(path)

    notices = [record.getMessage() for record in caplog.records if KEY in record.getMessage()]
    assert len(notices) == 1
    assert "no longer used" in notices[0]


def test_a_file_without_the_key_gives_no_loader_notice(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = write(tmp_path, UNSET)

    with caplog.at_level(logging.WARNING):
        load(path)

    assert not [record for record in caplog.records if "enabled" in record.getMessage()]
    assert deprecations(path) == []


def test_the_key_in_the_local_overlay_is_noticed_as_well(tmp_path: Path) -> None:
    path = write(tmp_path, "")
    (tmp_path / "abk.local.yaml").write_text(SET)

    assert deprecations(path) == [KEY]


def test_abk_config_prints_no_enabled_key_and_notices_the_key_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, SET)

    code = main(["--config", str(path), "config"])

    seen = capsys.readouterr()
    assert code == 0
    assert "enabled" not in yaml.safe_load(seen.out)["review"]
    assert seen.err.count(KEY) == 1
    assert "no longer used" in seen.err


def test_abk_config_says_nothing_of_a_file_without_the_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, UNSET)

    code = main(["--config", str(path), "config"])

    seen = capsys.readouterr()
    assert code == 0
    assert KEY not in seen.err
    assert "enabled" not in yaml.safe_load(seen.out)["review"]


def test_abk_doctor_warns_once_and_does_not_fail(tmp_path: Path) -> None:
    checks = doctor(tmp_path, SET)

    warned = [c for c in checks if c.status == "warn" and KEY in c.detail]
    assert len(warned) == 1
    assert "no longer used" in warned[0].detail
    assert [c for c in checks if c.name == "config"][0].status == "ok"


def test_abk_doctor_has_no_warning_for_a_file_without_the_key(tmp_path: Path) -> None:
    checks = doctor(tmp_path, UNSET)

    assert not [c for c in checks if KEY in c.detail + c.fix]


def test_the_init_template_does_not_write_the_key() -> None:
    assert "enabled" not in REVIEW_BLOCK
