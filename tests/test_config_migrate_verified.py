"""A migration is checked against the old document and the loader before its text is returned."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_build_kit import config
from agent_build_kit.config_migrate import ConfigMigrateError, migrate

MOVED = ("max_units_in_progress", "max_concurrent_stacks", "max_concurrent_restacks")
OLD = (
    "version: 1\n"
    "limits:\n"
    "  min_unit_lines: 300\n"
    "  max_units_in_progress: 3  # three\n"
    "  # stacks\n"
    "  max_concurrent_stacks: 2\n"
    "  max_concurrent_restacks: 1\n"
)


def expected_document(old: dict[str, Any]) -> dict[str, Any]:
    """The old document with `limits` renamed and the three moved, built in memory."""
    block = dict(old["limits"])
    moved = {key: block.pop(key) for key in MOVED if key in block}
    return {
        **{key: value for key, value in old.items() if key != "limits"},
        "global_limits": block,
        "project_limits": moved,
    }


def test_the_result_is_the_old_document_renamed_and_moved() -> None:
    migrated = migrate(OLD)

    assert yaml.safe_load(migrated.text) == expected_document(yaml.safe_load(OLD))


def test_the_result_loads_with_the_configuration_loader(tmp_path: Path) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(migrate(OLD).text)

    loaded = config.load(path)

    assert loaded.global_limits.min_unit_lines == 300
    assert loaded.project_limits.max_units_in_progress == 3
    assert loaded.project_limits.max_concurrent_stacks == 2
    assert loaded.project_limits.max_concurrent_restacks == 1
    assert config.deprecations(path) == []


def test_a_result_that_would_differ_is_never_returned() -> None:
    # The indented line above the setting belongs to the block scalar before it, not to the
    # setting, so lifting it as a comment would change the document.
    text = (
        "limits:\n"
        "  min_unit_lines: |\n"
        "    kept\n"
        "    # part of the text\n"
        "  max_units_in_progress: 5\n"
    )

    try:
        migrated = migrate(text)
    except ConfigMigrateError:
        return
    assert yaml.safe_load(migrated.text) == expected_document(yaml.safe_load(text))


def test_migrating_the_migrated_text_returns_it_unchanged() -> None:
    first = migrate(OLD)

    second = migrate(first.text)

    assert second.text == first.text
    assert second.moved == ()


def test_a_text_with_no_limits_and_no_moved_setting_is_unchanged() -> None:
    text = "# nothing here\nversion: 1\nglobal_limits:\n  min_unit_lines: 300\n"

    migrated = migrate(text)

    assert migrated.text == text
    assert migrated.moved == ()
