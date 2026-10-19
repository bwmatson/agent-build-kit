"""The text edit renames the old test-kind setting keys and changes no other byte."""

from __future__ import annotations

from agent_build_kit.config_migrate import migrate

BEFORE = (
    "version: 1\n"
    "global_limits:\n"
    "  min_unit_lines: 300\n"
    "  # how long to wait for the lock\n"
    "  tier2_lock_wait_seconds: 600  # ten minutes\n"
    "repos:\n"
    "  app:\n"
    "    path: app\n"
    "    tests:\n"
    "      # when the e2e tests run\n"
    "      tier2_schedule: weekly  # once a week\n"
    "tests:\n"
    "  # the split of the e2e tests, by name\n"
    "  tier2_splits:\n"
    "    slow:\n"
    "      tier2_schedule: nightly\n"
    "    fast: {}\n"
)
AFTER = (
    BEFORE.replace("tier2_lock_wait_seconds", "e2e_lock_wait_seconds")
    .replace("      tier2_schedule: weekly", "      e2e_schedule: weekly")
    .replace("  tier2_splits:", "  e2e_splits:")
)


def test_each_old_key_is_renamed_with_its_value_and_comments_as_they_were() -> None:
    migrated = migrate(BEFORE).text

    assert "  # how long to wait for the lock\n  e2e_lock_wait_seconds: 600  # ten minutes\n" in (
        migrated
    )
    assert "      # when the e2e tests run\n      e2e_schedule: weekly  # once a week\n" in migrated
    assert "  # the split of the e2e tests, by name\n  e2e_splits:\n" in migrated
    assert "tier2_lock_wait_seconds" not in migrated
    assert "tier2_splits" not in migrated
    assert "      tier2_schedule: weekly" not in migrated


def test_no_other_byte_changes_and_a_second_run_returns_the_same_text() -> None:
    migrated = migrate(BEFORE).text

    assert migrated != BEFORE
    assert migrated == AFTER
    assert migrate(migrated).text == migrated


def test_a_unit_test_key_is_renamed_to_its_stem() -> None:
    before = "global_limits:\n  tier1_repeat_runs: 2\n  tier1_command_seconds: 90  # slow\n"

    migrated = migrate(before).text

    assert migrated == (
        "global_limits:\n  unit_test_repeat_runs: 2\n  unit_test_command_seconds: 90  # slow\n"
    )


def test_values_are_never_renamed_only_keys() -> None:
    before = "repos:\n  app:\n    tests:\n      tier2_marker: tier2_marker\n"

    assert migrate(before).text == ("repos:\n  app:\n    tests:\n      e2e_marker: tier2_marker\n")


def test_the_edit_keeps_carriage_returns_and_a_missing_final_newline() -> None:
    before = "global_limits:\r\n  tier2_lock_wait_seconds: 600"

    assert migrate(before).text == "global_limits:\r\n  e2e_lock_wait_seconds: 600"
