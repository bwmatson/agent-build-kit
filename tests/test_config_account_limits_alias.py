"""`accounts.<label>.project_limits.max_units_in_progress` is the account's slot limit; the key
`max_units_in_progress` directly under an account still loads as it, is listed as deprecated, and
is refused beside the new place."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import claude_account, config
from agent_build_kit.config import AccountConfig

NOTICE = (
    "`runtimes.claude_code.accounts.kit.max_units_in_progress` is moved to "
    "`project_limits.max_units_in_progress`; `abk config --migrate` moves it"
)


def write(tmp_path: Path, text: str, name: str = "abk.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def account_text(tmp_path: Path, body: str) -> str:
    return (
        "runtimes:\n  claude_code:\n    accounts:\n      kit:\n"
        f"        config_dir: {tmp_path / 'kit-home'}\n{body}"
    )


OLD = "        max_units_in_progress: 3\n"
NEW = "        project_limits:\n          max_units_in_progress: 3\n"


def load_text(tmp_path: Path, local: str, base: str = "") -> config.WorkspaceConfig:
    path = write(tmp_path, "version: 1\n" + base)
    write(tmp_path, local, "abk.local.yaml")
    return config.load(path)


def account_of(loaded: config.WorkspaceConfig) -> AccountConfig:
    return loaded.runtimes["claude_code"].accounts["kit"]


def notices(path: Path) -> list[str]:
    return [config.deprecation_notice(key) for key in config.deprecations(path)]


def test_the_old_key_loads_as_the_blocks_value_and_sets_only_that_field(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, account_text(tmp_path, OLD))

    block = account_of(loaded).project_limits
    assert block.max_units_in_progress == 3
    assert block.model_fields_set == {"max_units_in_progress"}


def test_the_old_key_loads_to_the_same_account_as_the_new_place(tmp_path: Path) -> None:
    (tmp_path / "old").mkdir()
    (tmp_path / "new").mkdir()
    old = load_text(tmp_path / "old", account_text(tmp_path, OLD))
    new = load_text(tmp_path / "new", account_text(tmp_path, NEW))

    assert account_of(old) == account_of(new)
    assert account_of(old).project_limits.model_fields_set == (
        account_of(new).project_limits.model_fields_set
    )


def test_the_field_is_no_longer_an_attribute_of_the_account() -> None:
    assert "max_units_in_progress" not in AccountConfig.model_fields


def test_the_old_key_reaches_the_resolved_account_and_its_slot_limit(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, account_text(tmp_path, OLD))

    account = claude_account.resolve_in(loaded, "kit")

    assert account.project_limits.max_units_in_progress == 3
    assert account.project_limits.model_fields_set == {"max_units_in_progress"}


def test_the_old_key_beside_other_block_fields_keeps_them(tmp_path: Path) -> None:
    body = OLD + "        project_limits:\n          max_concurrent_stacks: 2\n"

    block = account_of(load_text(tmp_path, account_text(tmp_path, body))).project_limits

    assert block.max_units_in_progress == 3
    assert block.max_concurrent_stacks == 2
    assert block.model_fields_set == {"max_units_in_progress", "max_concurrent_stacks"}


def test_the_old_key_is_listed_with_the_notice_that_names_the_new_place(tmp_path: Path) -> None:
    write(tmp_path, "version: 1\n")
    write(tmp_path, account_text(tmp_path, OLD), "abk.local.yaml")

    assert NOTICE in notices(tmp_path / "abk.yaml")


def test_the_new_place_is_not_listed(tmp_path: Path) -> None:
    write(tmp_path, "version: 1\n")
    write(tmp_path, account_text(tmp_path, NEW), "abk.local.yaml")

    assert notices(tmp_path / "abk.yaml") == []


def test_both_places_set_is_refused_naming_both(tmp_path: Path) -> None:
    both = OLD + "        project_limits:\n          max_units_in_progress: 4\n"

    with pytest.raises(config.ConfigError) as refused:
        load_text(tmp_path, account_text(tmp_path, both))

    assert "`max_units_in_progress`" in str(refused.value)
    assert "`project_limits.max_units_in_progress`" in str(refused.value)
    assert "runtimes.claude_code.accounts.kit" in str(refused.value)


def test_both_places_in_one_account_are_refused() -> None:
    with pytest.raises(ValueError, match=r"project_limits\.max_units_in_progress"):
        AccountConfig.model_validate(
            {"max_units_in_progress": 2, "project_limits": {"max_units_in_progress": 3}}
        )


def test_a_model_built_with_the_old_keyword_still_works() -> None:
    account = AccountConfig.model_validate({"max_units_in_progress": 2})

    assert account.project_limits.max_units_in_progress == 2
    assert account.project_limits.model_fields_set == {"max_units_in_progress"}


def test_an_old_key_with_no_value_reads_as_unset(tmp_path: Path) -> None:
    body = "        max_units_in_progress:\n"

    block = account_of(load_text(tmp_path, account_text(tmp_path, body))).project_limits

    assert block.model_fields_set == set()


def test_the_base_file_and_the_overlay_may_spell_it_differently(tmp_path: Path) -> None:
    base = "runtimes:\n  claude_code:\n    accounts:\n      kit:\n        project_limits:\n"
    base += "          max_units_in_progress: 3\n          emergency_extra: 0\n"

    loaded = load_text(tmp_path, account_text(tmp_path, "        max_units_in_progress: 5\n"), base)

    block = account_of(loaded).project_limits
    assert block.max_units_in_progress == 5
    assert block.emergency_extra == 0


def test_an_invalid_value_is_reported_under_the_spelling_the_person_wrote(
    tmp_path: Path,
) -> None:
    with pytest.raises(config.ConfigError) as old:
        load_text(tmp_path, account_text(tmp_path, "        max_units_in_progress: 0\n"))
    assert "kit.max_units_in_progress" in str(old.value)
    assert "project_limits" not in str(old.value)

    with pytest.raises(config.ConfigError, match=r"kit\.project_limits\.max_units_in_progress"):
        load_text(tmp_path, account_text(tmp_path, NEW.replace(": 3", ": 0")))
