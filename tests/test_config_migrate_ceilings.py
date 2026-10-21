"""The text edit moves `max_unit_lines` to `review.ceilings.full` and changes no other byte."""

from __future__ import annotations

import yaml

from agent_build_kit.config_migrate import migrate

WITH_KEY = (
    "version: 1\n"
    "global_limits:\n"
    "  min_unit_lines: 300\n"
    "  # the biggest unit a person reads\n"
    "  # whole\n"
    "  max_unit_lines: 900  # nine hundred\n"
    "  max_review_rounds: 3\n"
    "repos:\n"
    "  app:\n"
    "    path: app\n"
)
MOVED_LINES = [
    "# the biggest unit a person reads",
    "# whole",
    "max_unit_lines: 900  # nine hundred",
]


def test_the_key_becomes_review_ceilings_full_with_its_value() -> None:
    migrated = yaml.safe_load(migrate(WITH_KEY).text)

    assert migrated["review"] == {"ceilings": {"full": 900}}
    assert migrated["global_limits"] == {"min_unit_lines": 300, "max_review_rounds": 3}


def test_the_comments_travel_and_every_other_line_is_as_it_was() -> None:
    migrated = migrate(WITH_KEY).text.splitlines()
    before = WITH_KEY.splitlines()

    kept = [line for line in before if line.strip() not in MOVED_LINES]
    assert [line for line in migrated if line in kept] == kept
    added = [line.strip() for line in migrated if line not in before]
    assert added == [
        "review:",
        "ceilings:",
        "# the biggest unit a person reads",
        "# whole",
        "full: 900  # nine hundred",
    ]
    assert not any("max_unit_lines" in line for line in migrated)


def test_the_comment_lines_stay_directly_above_the_key_they_describe() -> None:
    migrated = migrate(WITH_KEY).text.splitlines()

    at = next(i for i, line in enumerate(migrated) if line.strip().startswith("full:"))
    assert migrated[at - 2].strip() == "# the biggest unit a person reads"
    assert migrated[at - 1].strip() == "# whole"


def test_the_deprecated_root_limits_block_is_read_the_same_way() -> None:
    before = "version: 1\nlimits:\n  min_unit_lines: 300\n  max_unit_lines: 900  # cap\n"

    migrated = yaml.safe_load(migrate(before).text)

    assert migrated["review"] == {"ceilings": {"full": 900}}
    assert migrated["global_limits"] == {"min_unit_lines": 300}
    assert "limits" not in migrated


def test_an_existing_review_block_gets_ceilings_in_its_own_indentation() -> None:
    before = (
        "global_limits:\n"
        "    max_unit_lines: 900\n"
        "review:\n"
        "    enabled: false\n"
        "repos:\n"
        "    app:\n"
        "        path: app\n"
    )

    migrated = migrate(before).text

    assert "review:\n    enabled: false\n    ceilings:\n        full: 900\n" in migrated
    assert "max_unit_lines" not in migrated
    assert yaml.safe_load(migrated)["review"] == {"enabled": False, "ceilings": {"full": 900}}


def test_an_existing_ceilings_block_gets_the_key_beside_its_siblings() -> None:
    before = (
        "global_limits:\n"
        "  max_unit_lines: 900\n"
        "review:\n"
        "  ceilings:\n"
        "    auto: 4000\n"
        "    light: 2000\n"
    )

    migrated = migrate(before).text

    assert yaml.safe_load(migrated)["review"]["ceilings"] == {
        "auto": 4000,
        "light": 2000,
        "full": 900,
    }
    assert "    full: 900\n" in migrated
    assert "max_unit_lines" not in migrated


def test_an_emptied_global_limits_block_still_parses() -> None:
    migrated = yaml.safe_load(migrate("global_limits:\n  max_unit_lines: 900\n").text)

    assert migrated["review"] == {"ceilings": {"full": 900}}
    assert not migrated.get("global_limits")


def test_carriage_returns_and_a_missing_final_newline_are_kept() -> None:
    before = "global_limits:\r\n  max_unit_lines: 900\r\nrepos: {}"

    migrated = migrate(before).text

    assert not migrated.endswith("\n")
    assert migrated.count("\n") == migrated.count("\r\n")
    assert yaml.safe_load(migrated)["review"] == {"ceilings": {"full": 900}}


def test_a_second_run_returns_the_same_text() -> None:
    once = migrate(WITH_KEY).text

    assert once != WITH_KEY
    assert migrate(once).text == once
