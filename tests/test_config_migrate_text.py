"""The text edit that moves the limits: the key is renamed and the three settings move."""

from __future__ import annotations

from agent_build_kit.config_migrate import migrate


def test_the_three_move_with_their_comments_and_the_others_stay() -> None:
    text = (
        "version: 1\n"
        "limits:\n"
        "  # stays\n"
        "  stack_depth_build_cap: 3\n"
        "  # how many units\n"
        "  max_units_in_progress: 5  # five\n"
        "  max_concurrent_stacks: 4\n"
        "  min_unit_lines: 400  # stays too\n"
        "  # restacks\n"
        "  max_concurrent_restacks: 2  # two\n"
        "repos: {}\n"
    )

    migrated = migrate(text)

    assert migrated.text == (
        "version: 1\n"
        "global_limits:\n"
        "  # stays\n"
        "  stack_depth_build_cap: 3\n"
        "  min_unit_lines: 400  # stays too\n"
        "project_limits:\n"
        "  # how many units\n"
        "  max_units_in_progress: 5  # five\n"
        "  max_concurrent_stacks: 4\n"
        "  # restacks\n"
        "  max_concurrent_restacks: 2  # two\n"
        "repos: {}\n"
    )
    assert set(migrated.moved) == {
        "max_units_in_progress",
        "max_concurrent_stacks",
        "max_concurrent_restacks",
    }


def test_the_files_own_indentation_and_quoting_are_kept() -> None:
    text = (
        "limits:\n"
        "    min_unit_lines: 400\n"
        '    "max_units_in_progress": 5\n'
        "    'max_concurrent_stacks': 4\n"
    )

    assert migrate(text).text == (
        "global_limits:\n"
        "    min_unit_lines: 400\n"
        "project_limits:\n"
        '    "max_units_in_progress": 5\n'
        "    'max_concurrent_stacks': 4\n"
    )


def test_a_comment_after_the_block_stays_after_the_new_block() -> None:
    text = (
        "limits:\n  min_unit_lines: 400\n  max_concurrent_stacks: 4\n\n# repos below\nrepos: {}\n"
    )

    assert migrate(text).text == (
        "global_limits:\n"
        "  min_unit_lines: 400\n"
        "project_limits:\n"
        "  max_concurrent_stacks: 4\n"
        "\n# repos below\nrepos: {}\n"
    )


def test_a_block_holding_only_the_three_reads_empty() -> None:
    text = (
        "limits:\n"
        "  max_units_in_progress: 5\n"
        "  max_concurrent_stacks: 4\n"
        "  max_concurrent_restacks: 2\n"
    )

    assert migrate(text).text == (
        "global_limits: {}\n"
        "project_limits:\n"
        "  max_units_in_progress: 5\n"
        "  max_concurrent_stacks: 4\n"
        "  max_concurrent_restacks: 2\n"
    )


def test_a_global_limits_that_still_holds_one_moves_only_that() -> None:
    text = (
        "global_limits:\n"
        "  min_unit_lines: 400\n"
        "  # kept with it\n"
        "  max_concurrent_restacks: 2  # two\n"
        "repos: {}\n"
    )

    migrated = migrate(text)

    assert migrated.text == (
        "global_limits:\n"
        "  min_unit_lines: 400\n"
        "project_limits:\n"
        "  # kept with it\n"
        "  max_concurrent_restacks: 2  # two\n"
        "repos: {}\n"
    )
    assert migrated.moved == ("max_concurrent_restacks",)
