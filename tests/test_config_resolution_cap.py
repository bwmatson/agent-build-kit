"""`project_limits.max_concurrent_resolutions`: how many runs the resolution lane holds at once.
The old key `max_concurrent_restacks` loads as it with a deprecation notice, is refused beside it,
is renamed by `abk config --migrate`, and is noticed line by line in the overlay."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agent_build_kit import config
from agent_build_kit.cli import main
from agent_build_kit.config import ProjectLimitsConfig
from agent_build_kit.config_migrate import ConfigMigrateError, migrate

OLD = (
    "version: 1\n"
    "project_limits:\n"
    "  max_concurrent_stacks: 2\n"
    "  # resolutions\n"
    "  max_concurrent_restacks: 3  # three\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    accounts:\n"
    "      kit:\n"
    "        project_limits:\n"
    "          max_concurrent_restacks: 1\n"
)
NEW = OLD.replace("max_concurrent_restacks", "max_concurrent_resolutions")
OVERLAY = "project_limits:\n  max_concurrent_restacks: 3\n"


def limits(**values: Any) -> Any:
    return ProjectLimitsConfig.model_validate(values)


def write(tmp_path: Path, text: str, name: str = "abk.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def dumped(directory: Path, text: str) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    return config.load(write(directory, text)).model_dump(mode="json")


def test_two_resolutions_run_at_once_by_default() -> None:
    assert limits().max_concurrent_resolutions == 2


@pytest.mark.parametrize("value", [0, -1, 1.5, "two"])
def test_a_cap_that_is_not_a_positive_whole_number_is_refused_by_name(value: object) -> None:
    with pytest.raises(ValidationError, match="max_concurrent_resolutions"):
        limits(max_concurrent_resolutions=value)


def test_the_old_key_loads_as_the_same_value(tmp_path: Path) -> None:
    text = "version: 1\nproject_limits:\n  max_concurrent_restacks: 3\n"

    loaded = config.load(write(tmp_path, text))

    assert loaded.project_limits.model_dump()["max_concurrent_resolutions"] == 3


def test_the_old_key_loads_to_the_same_configuration_as_the_new_one(tmp_path: Path) -> None:
    assert dumped(tmp_path / "old", OLD) == dumped(tmp_path / "new", NEW)


def test_the_old_key_is_listed_with_a_notice_naming_both_and_the_command(tmp_path: Path) -> None:
    path = write(tmp_path, OLD)

    notices = [config.deprecation_notice(key) for key in config.deprecations(path)]

    assert any(
        "max_concurrent_restacks" in notice
        and "max_concurrent_resolutions" in notice
        and "abk config --migrate" in notice
        for notice in notices
    ), notices


def test_the_new_key_is_not_listed(tmp_path: Path) -> None:
    assert config.deprecations(write(tmp_path, NEW)) == []
    assert dumped(tmp_path / "new", NEW)["project_limits"]["max_concurrent_resolutions"] == 3


def test_both_keys_set_is_refused_naming_both(tmp_path: Path) -> None:
    both = (
        "version: 1\nproject_limits:\n"
        "  max_concurrent_restacks: 3\n  max_concurrent_resolutions: 4\n"
    )

    with pytest.raises(config.ConfigError) as refused:
        config.load(write(tmp_path, both))

    assert "max_concurrent_restacks" in str(refused.value)
    assert "max_concurrent_resolutions" in str(refused.value)


def test_the_migration_renames_the_key_in_place_and_changes_no_other_byte() -> None:
    migrated = migrate(OLD).text

    assert migrated != OLD
    assert migrated == NEW


def test_the_migrated_file_loads_to_the_configuration_it_had(tmp_path: Path) -> None:
    migrated = migrate(OLD).text
    assert migrated != OLD

    assert dumped(tmp_path / "before", OLD) == dumped(tmp_path / "after", migrated)


def test_a_second_run_changes_nothing() -> None:
    first = migrate(OLD).text

    assert first != OLD
    assert migrate(first).text == first


ANCHORED = OLD.replace("restacks: 3", "restacks: &n 3")
BOTH = OLD.replace(
    "  max_concurrent_restacks: 3  # three\n",
    "  max_concurrent_restacks: 3\n  max_concurrent_resolutions: 4\n",
)


@pytest.mark.parametrize(("text", "reason"), [(ANCHORED, r"anchor|alias"), (BOTH, r"both|already")])
def test_a_form_that_cannot_be_edited_by_lines_is_refused_naming_the_key(
    text: str, reason: str
) -> None:
    with pytest.raises(ConfigMigrateError) as refused:
        migrate(text)

    assert "max_concurrent_restacks" in str(refused.value)
    assert re.search(reason, str(refused.value))


def test_the_overlay_is_left_alone_and_each_line_to_change_is_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "version: 1\n")
    overlay = write(tmp_path, OVERLAY, "abk.local.yaml")

    code = main(["--config", str(path), "config"])

    err = capsys.readouterr().err
    assert code == 0
    assert overlay.read_text() == OVERLAY
    assert re.search(r"abk\.local\.yaml:2\b", err), err
    assert "max_concurrent_resolutions" in err


def test_both_keys_in_one_accounts_block_are_refused_naming_the_account(tmp_path: Path) -> None:
    both = OLD.replace(
        "          max_concurrent_restacks: 1\n",
        "          max_concurrent_restacks: 1\n          max_concurrent_resolutions: 2\n",
    )

    with pytest.raises(config.ConfigError) as refused:
        config.load(write(tmp_path, both))

    assert "runtimes.claude_code.accounts.kit.project_limits" in str(refused.value)
