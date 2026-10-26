"""The text edit renames `limits` under each runtime and account to `usage_limits` and changes no
other byte; the rewritten file loads to the configuration it had."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_build_kit import config
from agent_build_kit.config_migrate import migrate

BEFORE = (
    "version: 1\n"
    "repos:\n"
    "  app:\n"
    "    slug: example/app\n"
    "    profile: python-uv\n"
    "    path: ../app\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    # the usage windows\n"
    "    limits:  # pause early\n"
    "      session:\n"
    "        usage_pause_pct: 62\n"
    "    accounts:\n"
    "      kit:\n"
    "        # this account's windows\n"
    "        limits:\n"
    "          session:\n"
    "            usage_pause_pct: 55\n"
    "      spare:\n"
    "        limits:\n"
    "          weekly:\n"
    "            usage_pause_pct: 80\n"
    "global_limits:\n"
    "  min_unit_lines: 300\n"
)
AFTER = BEFORE.replace("    limits:  # pause", "    usage_limits:  # pause").replace(
    "        limits:\n", "        usage_limits:\n"
)


def loaded(directory: Path, text: str) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "abk.yaml"
    path.write_text(text)
    return config.load(path).model_dump(mode="json")


def test_the_key_is_renamed_under_the_runtime_and_each_account_and_no_other_byte_changes() -> None:
    migrated = migrate(BEFORE).text

    assert migrated != BEFORE
    assert migrated == AFTER
    assert "    # the usage windows\n    usage_limits:  # pause early\n" in migrated
    assert "        # this account's windows\n        usage_limits:\n" in migrated


def test_key_order_is_kept() -> None:
    migrated = yaml.safe_load(migrate(BEFORE).text)

    assert list(migrated["runtimes"]["claude_code"]) == ["usage_limits", "accounts"]
    assert list(migrated["runtimes"]["claude_code"]["accounts"]) == ["kit", "spare"]


def test_the_rewritten_file_loads_to_the_same_configuration(tmp_path: Path) -> None:
    assert loaded(tmp_path / "before", BEFORE) == loaded(tmp_path / "after", migrate(BEFORE).text)


def test_the_result_is_the_old_document_with_the_key_renamed() -> None:
    old = yaml.safe_load(BEFORE)
    runtime = old["runtimes"]["claude_code"]
    accounts = {
        name: {
            ("usage_limits" if key == "limits" else key): value for key, value in account.items()
        }
        for name, account in runtime["accounts"].items()
    }
    expected = {
        **old,
        "runtimes": {"claude_code": {"usage_limits": runtime["limits"], "accounts": accounts}},
    }

    assert yaml.safe_load(migrate(BEFORE).text) == expected


def test_a_second_run_changes_nothing() -> None:
    first = migrate(BEFORE).text

    assert first == AFTER
    assert migrate(first).text == first


def test_the_root_limits_key_still_becomes_global_limits_beside_the_rename() -> None:
    before = "limits:\n  min_unit_lines: 300\nruntimes:\n  claude_code:\n    limits: {}\n"

    assert yaml.safe_load(migrate(before).text) == {
        "global_limits": {"min_unit_lines": 300},
        "runtimes": {"claude_code": {"usage_limits": {}}},
    }


def test_an_account_already_on_the_new_key_is_left_as_it_is() -> None:
    before = (
        "runtimes:\n  claude_code:\n    accounts:\n"
        "      kit:\n        usage_limits: {}\n      spare:\n        limits: {}\n"
    )

    assert migrate(before).text == before.replace("        limits:", "        usage_limits:")


def test_only_keys_are_renamed_never_values() -> None:
    before = "runtimes:\n  claude_code:\n    limits:\n      note: limits\n"

    assert migrate(before).text == (
        "runtimes:\n  claude_code:\n    usage_limits:\n      note: limits\n"
    )


def test_the_edit_keeps_carriage_returns_and_a_missing_final_newline() -> None:
    before = "runtimes:\r\n  claude_code:\r\n    limits:\r\n      session: {}"

    assert migrate(before).text == (
        "runtimes:\r\n  claude_code:\r\n    usage_limits:\r\n      session: {}"
    )
