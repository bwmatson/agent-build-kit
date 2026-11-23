"""The text edit moves `max_units_in_progress` under an account into the account's
`project_limits` block and changes no other byte; the rewritten file loads to the configuration it
had, a second run changes nothing, and a form that cannot be edited by lines is refused naming the
key."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.config_migrate import ConfigMigrateError, migrate

BEFORE = (
    "version: 1\n"
    "repos:\n"
    "  app:\n"
    "    slug: example/app\n"
    "    profile: python-uv\n"
    "    path: ../app\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    accounts:\n"
    "      kit:\n"
    "        usage_limits:\n"
    "          session:\n"
    "            usage_pause_pct: 55\n"
    "        # this account's slots\n"
    "        max_units_in_progress: 3  # its own\n"
    "      spare:\n"
    "        max_units_in_progress: 1\n"
    "        project_limits:\n"
    "          max_concurrent_stacks: 2\n"
    "          # restacks\n"
    "          max_concurrent_resolutions: 1\n"
    "      third:\n"
    "        project_limits:\n"
    "          max_units_in_progress: 4\n"
    "      bare:\n"
    "        project_limits:\n"
    "        max_units_in_progress: 2\n"
    "global_limits:\n"
    "  min_unit_lines: 300\n"
)
AFTER = (
    "version: 1\n"
    "repos:\n"
    "  app:\n"
    "    slug: example/app\n"
    "    profile: python-uv\n"
    "    path: ../app\n"
    "runtimes:\n"
    "  claude_code:\n"
    "    accounts:\n"
    "      kit:\n"
    "        usage_limits:\n"
    "          session:\n"
    "            usage_pause_pct: 55\n"
    "        project_limits:\n"
    "          # this account's slots\n"
    "          max_units_in_progress: 3  # its own\n"
    "      spare:\n"
    "        project_limits:\n"
    "          max_concurrent_stacks: 2\n"
    "          # restacks\n"
    "          max_concurrent_resolutions: 1\n"
    "          max_units_in_progress: 1\n"
    "      third:\n"
    "        project_limits:\n"
    "          max_units_in_progress: 4\n"
    "      bare:\n"
    "        project_limits:\n"
    "          max_units_in_progress: 2\n"
    "global_limits:\n"
    "  min_unit_lines: 300\n"
)


def loaded(directory: Path, text: str) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "abk.yaml"
    path.write_text(text)
    return config.load(path).model_dump(mode="json")


def test_the_key_moves_into_each_accounts_block_and_no_other_byte_changes() -> None:
    migrated = migrate(BEFORE).text

    assert migrated == AFTER


def test_the_comments_above_the_key_and_after_it_go_with_it() -> None:
    migrated = migrate(BEFORE).text

    assert (
        "        project_limits:\n          # this account's slots\n"
        "          max_units_in_progress: 3  # its own\n"
    ) in migrated


def test_the_key_joins_a_block_the_account_already_has() -> None:
    accounts = yaml.safe_load(migrate(BEFORE).text)["runtimes"]["claude_code"]["accounts"]

    assert accounts["spare"]["project_limits"] == {
        "max_concurrent_stacks": 2,
        "max_concurrent_resolutions": 1,
        "max_units_in_progress": 1,
    }
    assert "max_units_in_progress" not in accounts["spare"]


def test_the_rewritten_file_loads_to_the_same_configuration(tmp_path: Path) -> None:
    assert loaded(tmp_path / "before", BEFORE) == loaded(tmp_path / "after", migrate(BEFORE).text)


def test_the_result_is_the_old_document_with_the_key_moved() -> None:
    old = yaml.safe_load(BEFORE)
    accounts = {}
    for label, account in old["runtimes"]["claude_code"]["accounts"].items():
        rest = {key: value for key, value in account.items() if key != "max_units_in_progress"}
        if "max_units_in_progress" in account:
            rest["project_limits"] = {
                **(account.get("project_limits") or {}),
                "max_units_in_progress": account["max_units_in_progress"],
            }
        accounts[label] = rest
    expected = {**old, "runtimes": {"claude_code": {"accounts": accounts}}}

    assert yaml.safe_load(migrate(BEFORE).text) == expected


def test_a_second_run_changes_nothing() -> None:
    first = migrate(BEFORE).text

    assert first == AFTER
    assert migrate(first).text == first


def test_a_file_with_nothing_to_move_is_returned_as_it_is() -> None:
    assert migrate(AFTER).text == AFTER


def test_an_indent_other_than_two_is_kept() -> None:
    before = (
        "runtimes:\n    claude_code:\n        accounts:\n            kit:\n"
        "                max_units_in_progress: 3\n"
    )

    assert migrate(before).text == (
        "runtimes:\n    claude_code:\n        accounts:\n            kit:\n"
        "                project_limits:\n                    max_units_in_progress: 3\n"
    )


def test_the_root_limits_move_and_the_account_move_work_in_one_file() -> None:
    before = (
        "limits:\n  max_units_in_progress: 7\n"
        "runtimes:\n  claude_code:\n    accounts:\n      kit:\n        max_units_in_progress: 3\n"
    )

    assert yaml.safe_load(migrate(before).text) == {
        "global_limits": {},
        "project_limits": {"max_units_in_progress": 7},
        "runtimes": {
            "claude_code": {"accounts": {"kit": {"project_limits": {"max_units_in_progress": 3}}}}
        },
    }


def test_only_keys_are_moved_never_values() -> None:
    before = (
        "runtimes:\n  claude_code:\n    accounts:\n      kit:\n"
        "        note: max_units_in_progress\n"
    )

    assert migrate(before).text == before


def test_the_edit_keeps_carriage_returns_and_a_missing_final_newline() -> None:
    before = (
        "runtimes:\r\n  claude_code:\r\n    accounts:\r\n      kit:\r\n"
        "        max_units_in_progress: 3"
    )

    assert migrate(before).text == (
        "runtimes:\r\n  claude_code:\r\n    accounts:\r\n      kit:\r\n"
        "        project_limits:\r\n          max_units_in_progress: 3"
    )


# name -> (text, a pattern for the key the message names, a pattern for the reason it gives)
HEAD = "runtimes:\n  claude_code:\n    accounts:\n      kit:\n"
CASES = {
    "both places in one account": (
        HEAD + "        max_units_in_progress: 3\n        project_limits:\n"
        "          max_units_in_progress: 4\n",
        r"max_units_in_progress",
        r"both|together",
    ),
    "anchor on the key": (
        HEAD + "        max_units_in_progress: &n 3\n",
        r"max_units_in_progress",
        r"anchor|alias",
    ),
    "alias as the value": (
        "n: &n 3\n" + HEAD + "        max_units_in_progress: *n\n",
        r"max_units_in_progress",
        r"anchor|alias",
    ),
    "anchor on the account": (
        "runtimes:\n  claude_code:\n    accounts:\n      kit: &k\n"
        "        max_units_in_progress: 3\n",
        r"kit|max_units_in_progress",
        r"anchor|alias",
    ),
    "an account reached by two names": (
        "runtimes:\n  claude_code:\n    accounts:\n      kit: &k\n"
        "        max_units_in_progress: 3\n      spare: *k\n",
        r"kit|spare|max_units_in_progress",
        r"merge|alias|anchor",
    ),
    "a runtime reached by two names": (
        "runtimes:\n  claude_code: &rt\n    accounts:\n      kit:\n"
        "        max_units_in_progress: 3\n  other: *rt\n",
        r"runtimes\.(claude_code|other)|max_units_in_progress",
        r"merge|alias|anchor",
    ),
    "merge key in the account": (
        "base: &base\n  max_units_in_progress: 3\n" + HEAD + "        <<: *base\n",
        r"max_units_in_progress|kit",
        r"merge",
    ),
    "accounts merged into a runtime": (
        "base: &base\n  accounts:\n    kit:\n      max_units_in_progress: 3\n"
        "runtimes:\n  claude_code:\n    <<: *base\n",
        r"max_units_in_progress",
        r"merge",
    ),
    "the key under an account merged into the accounts mapping": (
        "more: &more\n  kit:\n    max_units_in_progress: 3\nruntimes:\n  claude_code:\n"
        "    accounts:\n      <<: *more\n",
        r"max_units_in_progress",
        r"merge",
    ),
    "flow-style account": (
        "runtimes:\n  claude_code:\n    accounts:\n      kit: {max_units_in_progress: 3}\n",
        r"kit|max_units_in_progress",
        r"flow",
    ),
    "flow-style accounts": (
        "runtimes:\n  claude_code:\n    accounts: {kit: {max_units_in_progress: 3}}\n",
        r"accounts|max_units_in_progress",
        r"flow",
    ),
    "flow-style project_limits": (
        HEAD + "        max_units_in_progress: 3\n        project_limits: {emergency_extra: 0}\n",
        r"project_limits",
        r"flow",
    ),
    "anchor on project_limits": (
        HEAD + "        max_units_in_progress: 3\n        project_limits: &p\n"
        "          emergency_extra: 0\n",
        r"project_limits",
        r"anchor|alias",
    ),
    "project_limits that is not a mapping": (
        HEAD + "        max_units_in_progress: 3\n        project_limits: 4\n",
        r"project_limits",
        r"not a mapping",
    ),
    "a quoted key": (
        HEAD + '        "max_units_in_progress": 3\n',
        r"max_units_in_progress",
        r"quoted",
    ),
    "a value on another line": (
        HEAD + "        max_units_in_progress:\n          3\n",
        r"max_units_in_progress",
        r"more than one line",
    ),
    "a key with no value": (
        HEAD + "        max_units_in_progress:\n",
        r"max_units_in_progress",
        r"no value|empty|null",
    ),
    "several documents": (
        HEAD + "        max_units_in_progress: 3\n---\nversion: 1\n",
        r"abk\.yaml",
        r"several documents",
    ),
}


@pytest.mark.parametrize("name", CASES)
def test_each_unsupported_form_is_refused_with_the_key_and_a_reason(name: str) -> None:
    text, key, reason = CASES[name]

    with pytest.raises(ConfigMigrateError) as refused:
        migrate(text)

    assert re.search(key, str(refused.value)), str(refused.value)
    assert re.search(reason, str(refused.value), re.IGNORECASE), str(refused.value)
