"""The migration changes only the lines it names, whatever the file's quirks."""

from __future__ import annotations

from collections import Counter

from agent_build_kit.config_migrate import migrate

# A directive, `---`, `~` and `null`, spaces before values and comments, a four-space block in a
# two-space file, CRLF, a trailing `...` and no final newline.
BEFORE = (
    "%YAML 1.2\r\n"
    "---\r\n"
    "# top\r\n"
    "name:   ~   # tilde\r\n"
    "repos:\r\n"
    "  app:\r\n"
    "    path:   app\r\n"
    "limits:\r\n"
    "    min_unit_lines:   null   # none\r\n"
    "    # stacks\r\n"
    "    max_concurrent_stacks:    4   # four\r\n"
    "    max_units_in_progress: 5\r\n"
    "other: x\r\n"
    "..."
)
AFTER = (
    "%YAML 1.2\r\n"
    "---\r\n"
    "# top\r\n"
    "name:   ~   # tilde\r\n"
    "repos:\r\n"
    "  app:\r\n"
    "    path:   app\r\n"
    "global_limits:\r\n"
    "    min_unit_lines:   null   # none\r\n"
    "project_limits:\r\n"
    "    # stacks\r\n"
    "    max_concurrent_stacks:    4   # four\r\n"
    "    max_units_in_progress: 5\r\n"
    "other: x\r\n"
    "..."
)


def test_only_the_renamed_key_and_the_moved_lines_differ() -> None:
    migrated = migrate(BEFORE).text

    assert migrated == AFTER
    before, after = Counter(BEFORE.splitlines(True)), Counter(migrated.splitlines(True))
    assert before - after == Counter(["limits:\r\n"])
    assert after - before == Counter(["global_limits:\r\n", "project_limits:\r\n"])


def test_a_trailing_document_end_is_still_last_and_no_newline_is_added() -> None:
    migrated = migrate(BEFORE).text

    assert migrated.endswith("other: x\r\n...")


def test_a_file_with_no_final_newline_gets_none() -> None:
    text = "limits:\n  max_concurrent_stacks: 4"

    assert migrate(text).text == "global_limits: {}\nproject_limits:\n  max_concurrent_stacks: 4"
