"""The old test-kind settings keys (`tier1_*`, `tier2_*`) load as the new ones (`unit_test_*`,
`e2e_*`), `abk config` and `abk doctor` say so, and a file holding both spellings is refused."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.cli import main
from agent_build_kit.cli.doctor import Check, run_doctor
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo

GLOBAL_PAIRS = {
    "tier2_lock_wait_seconds": ("e2e_lock_wait_seconds", "600"),
    "tier1_command_seconds": ("unit_test_command_seconds", "900"),
    "tier2_base_runs": ("e2e_base_runs", "0"),
    "tier2_schedule": ("e2e_schedule", "daily"),
    "tier1_abort_grace_seconds": ("unit_test_abort_grace_seconds", "20"),
    "tier1_repeat_runs": ("unit_test_repeat_runs", "5"),
    "tier2_unit_scope": ("e2e_unit_scope", "full"),
    "tier2_durations_shown": ("e2e_durations_shown", "5"),
}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return path


def limits_block(key: str, value: str) -> str:
    return f"version: 1\nglobal_limits:\n  {key}: {value}\n"


def repo_block(key: str, value: str) -> str:
    return (
        "version: 1\nrepos:\n  app:\n    path: /srv/app\n    slug: example/app\n"
        f"    tests:\n      {key}: {value}\n"
    )


@pytest.mark.parametrize("old", sorted(GLOBAL_PAIRS))
def test_each_old_limit_loads_as_its_new_key_with_the_same_value(tmp_path: Path, old: str) -> None:
    new, value = GLOBAL_PAIRS[old]

    from_old = config.load(write(tmp_path, limits_block(old, value)))
    from_new = config.load(write(tmp_path, limits_block(new, value)))

    assert from_old == from_new
    assert from_old != config.load(write(tmp_path, "version: 1\n"))


def test_an_error_names_a_setting_as_the_file_spells_it(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="tier2_lock_wait_seconds"):
        config.load(write(tmp_path, limits_block("tier2_lock_wait_seconds", "-5")))
    with pytest.raises(config.ConfigError, match="e2e_lock_wait_seconds"):
        config.load(write(tmp_path, limits_block("e2e_lock_wait_seconds", "-5")))


def test_an_old_key_is_validated_like_the_new_one(tmp_path: Path) -> None:
    with pytest.raises(config.ConfigError, match="greater than 0"):
        config.load(write(tmp_path, limits_block("e2e_lock_wait_seconds", "-5")))
    with pytest.raises(config.ConfigError, match="greater than 0"):
        config.load(write(tmp_path, limits_block("tier2_lock_wait_seconds", "-5")))


@pytest.mark.parametrize(
    ("old", "new", "value"),
    [
        ("tier2_marker", "e2e_marker", "slow"),
        ("tier2_schedule", "e2e_schedule", "daily"),
        ("tier2_unit_scope", "e2e_unit_scope", "full"),
        ("tier2_splits", "e2e_splits", "{slow: {marker: slow}}"),
    ],
)
def test_a_per_repo_tests_block_is_read_the_same_way(
    tmp_path: Path, old: str, new: str, value: str
) -> None:
    from_old = config.load(write(tmp_path, repo_block(old, value)))
    from_new = config.load(write(tmp_path, repo_block(new, value)))

    assert from_old == from_new
    assert from_old != config.load(write(tmp_path, repo_block("tier2_marker", "local_stack")))


@pytest.mark.parametrize("key", ["tier2_marker", "e2e_marker"])
def test_a_repo_named_with_a_dot_loads_with_its_tests_block(tmp_path: Path, key: str) -> None:
    text = repo_block(key, "slow").replace("  app:", "  my.app:")

    loaded = config.load(write(tmp_path, text))

    assert loaded.repos["my.app"].tests.tier2_marker == "slow"


def test_the_top_level_tests_block_is_read_the_same_way(tmp_path: Path) -> None:
    split = "    slow:\n      marker: slow\n"
    old = config.load(write(tmp_path, f"version: 1\ntests:\n  tier2_splits:\n{split}"))
    new = config.load(write(tmp_path, f"version: 1\ntests:\n  e2e_splits:\n{split}"))

    assert old == new
    assert old.tests.tier2_splits.keys() == {"slow"}


@pytest.mark.parametrize(
    ("old", "new", "text"),
    [
        (
            "tier2_schedule",
            "e2e_schedule",
            "version: 1\nglobal_limits:\n  tier2_schedule: daily\n  e2e_schedule: daily\n",
        ),
        (
            "tier2_splits",
            "e2e_splits",
            "version: 1\ntests:\n  tier2_splits: {a: {marker: a}}\n  e2e_splits: {a: {marker: a}}",
        ),
        (
            "tier1_repeat_runs",
            "unit_test_repeat_runs",
            "version: 1\nglobal_limits:\n  tier1_repeat_runs: 2\n  unit_test_repeat_runs: 2\n",
        ),
    ],
)
def test_both_spellings_of_one_setting_are_refused_naming_both_and_saying_to_keep_one(
    tmp_path: Path, old: str, new: str, text: str
) -> None:
    with pytest.raises(config.ConfigError) as refused:
        config.load(write(tmp_path, text))

    message = str(refused.value)
    assert old in message
    assert new in message
    assert "keep one" in message


def test_both_spellings_in_a_per_repo_block_are_refused_naming_both(tmp_path: Path) -> None:
    text = repo_block("tier2_marker", "slow") + "      e2e_marker: slow\n"

    with pytest.raises(config.ConfigError, match="keep one") as refused:
        config.load(write(tmp_path, text))

    assert "tier2_marker" in str(refused.value)
    assert "e2e_marker" in str(refused.value)


def run_config(
    tmp_path: Path, text: str, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    code = main(["--config", str(write(tmp_path, text)), "config"])
    seen = capsys.readouterr()
    return code, seen.out, seen.err


def test_abk_config_prints_only_new_keys_and_one_notice_per_old_key_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "version: 1\nglobal_limits:\n  tier2_lock_wait_seconds: 600\n  tier1_repeat_runs: 2\n"

    code, out, err = run_config(tmp_path, text, capsys)

    assert code == 0
    printed = yaml.safe_load(out)["global_limits"]
    assert printed["e2e_lock_wait_seconds"] == 600
    assert printed["unit_test_repeat_runs"] == 2
    assert "tier1" not in out
    assert "tier2" not in out
    assert err.count("tier2_lock_wait_seconds") == 1
    assert err.count("tier1_repeat_runs") == 1
    assert "e2e_lock_wait_seconds" in err
    assert "unit_test_repeat_runs" in err


def test_abk_config_says_nothing_of_the_kind_for_the_new_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_config(tmp_path, limits_block("e2e_lock_wait_seconds", "600"), capsys)

    assert code == 0
    assert yaml.safe_load(out)["global_limits"]["e2e_lock_wait_seconds"] == 600
    assert "deprecated" not in err


def doctor(tmp_path: Path, text: str) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    (planning / "abk.yaml").write_text(text)
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def test_abk_doctor_warns_once_per_old_key_naming_the_new_one_and_does_not_fail(
    tmp_path: Path,
) -> None:
    checks = doctor(tmp_path, limits_block("tier2_lock_wait_seconds", "600"))

    warned = [check for check in checks if check.status == "warn" and "tier2" in check.detail]
    assert len(warned) == 1
    assert "e2e_lock_wait_seconds" in warned[0].detail + warned[0].fix
    assert [check for check in checks if check.name == "config"][0].status == "ok"


def test_abk_doctor_has_no_warning_for_the_new_keys(tmp_path: Path) -> None:
    checks = doctor(tmp_path, limits_block("e2e_lock_wait_seconds", "600"))

    assert [check for check in checks if check.name == "config"][0].status == "ok"
    assert not [check for check in checks if "deprecated" in check.detail + check.fix]
