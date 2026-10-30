"""`runtimes.<n>.usage_limits` (and an account's) is the usage windows' key; `limits` there still
loads, is listed as deprecated, and is refused beside the new key."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import claude_account, config
from agent_build_kit.config import AccountConfig, RuntimeConfig
from agent_build_kit.pipeline import usage_guard

NOTICE = (
    "`runtimes.claude_code.limits` is renamed `usage_limits`; `abk config --migrate` renames it"
)
ACCOUNT_NOTICE = (
    "`runtimes.claude_code.accounts.kit.limits` is renamed `usage_limits`; "
    "`abk config --migrate` renames it"
)
PAUSE = {"session": {"usage_pause_pct": 62}}


def write(tmp_path: Path, text: str, name: str = "abk.yaml") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def runtime_block(key: str, pct: int = 60) -> str:
    return (
        f"runtimes:\n  claude_code:\n    {key}:\n      session:\n        usage_pause_pct: {pct}\n"
    )


def account_block(key: str, pct: int = 55) -> str:
    return (
        "runtimes:\n  claude_code:\n    accounts:\n      kit:\n        config_dir: /x/kit\n"
        f"        {key}:\n          session:\n            usage_pause_pct: {pct}\n"
    )


def load_text(tmp_path: Path, text: str, local: str | None = None) -> config.WorkspaceConfig:
    path = write(tmp_path, "version: 1\n" + text)
    if local is not None:
        write(tmp_path, local, "abk.local.yaml")
    return config.load(path)


def notices(path: Path) -> list[str]:
    return [config.deprecation_notice(key) for key in config.deprecations(path)]


def test_the_new_key_reaches_the_runtime_and_the_usage_guard(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, runtime_block("usage_limits"))
    config.activate(loaded)

    assert loaded.runtimes["claude_code"].usage_limits.session.usage_pause_pct == 60
    assert usage_guard.claude_limits().session.usage_pause_pct == 60


def test_the_old_key_loads_as_the_same_value(tmp_path: Path) -> None:
    old = load_text(tmp_path, runtime_block("limits"))
    new = load_text(tmp_path, runtime_block("usage_limits"))

    assert old.runtimes["claude_code"].usage_limits == new.runtimes["claude_code"].usage_limits


def test_the_old_key_is_listed_with_the_notice_that_names_the_new_one(tmp_path: Path) -> None:
    path = write(tmp_path, "version: 1\n" + runtime_block("limits"))

    assert NOTICE in notices(path)


def test_an_accounts_new_key_reaches_the_resolved_account(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, "", local=account_block("usage_limits"))

    account = claude_account.resolve_in(loaded, "kit")

    assert account.usage_limits.session.usage_pause_pct == 55
    with usage_guard.on_account(account):
        assert usage_guard.claude_limits().session.usage_pause_pct == 55


def test_an_accounts_old_key_loads_and_is_listed(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, "", local=account_block("limits"))
    account = claude_account.resolve_in(loaded, "kit")

    assert account.usage_limits.session.usage_pause_pct == 55
    assert ACCOUNT_NOTICE in notices(tmp_path / "abk.yaml")


def test_a_mapping_that_sets_both_is_refused_naming_both(tmp_path: Path) -> None:
    both = (
        "runtimes:\n  claude_code:\n    limits:\n      weekly:\n        usage_pause_pct: 50\n"
        "    usage_limits:\n      weekly:\n        usage_pause_pct: 60\n"
    )

    with pytest.raises(config.ConfigError) as refused:
        load_text(tmp_path, both)

    assert "`limits`" in str(refused.value)
    assert "`usage_limits`" in str(refused.value)


def test_both_spellings_in_one_account_are_refused() -> None:
    with pytest.raises(ValueError, match="usage_limits"):
        AccountConfig.model_validate({"limits": {}, "usage_limits": {}})


def test_the_base_file_and_the_overlay_may_spell_the_key_differently(tmp_path: Path) -> None:
    base = runtime_block("limits", pct=60) + "      weekly:\n        usage_pause_pct: 50\n"
    loaded = load_text(tmp_path, base, local=runtime_block("usage_limits", pct=65))

    merged = loaded.runtimes["claude_code"].usage_limits
    assert merged.session.usage_pause_pct == 65
    assert merged.weekly.usage_pause_pct == 50


def test_a_model_built_with_the_limits_keyword_still_works() -> None:
    runtime = RuntimeConfig.model_validate({"limits": PAUSE})
    account = AccountConfig.model_validate({"limits": PAUSE})

    assert runtime.usage_limits.session.usage_pause_pct == 62
    assert account.usage_limits.session.usage_pause_pct == 62


def test_usage_limits_on_another_runtime_is_refused_with_the_new_name(tmp_path: Path) -> None:
    text = "runtimes:\n  other:\n    usage_limits:\n      session:\n        usage_pause_pct: 60\n"

    with pytest.raises(config.ConfigError, match=r"runtimes\.other\.usage_limits"):
        load_text(tmp_path, text)


def test_an_invalid_value_is_reported_under_the_spelling_the_person_wrote(
    tmp_path: Path,
) -> None:
    with pytest.raises(config.ConfigError) as old:
        load_text(tmp_path, runtime_block("limits", pct=150))
    assert "limits.session.usage_pause_pct" in str(old.value)
    assert "usage_limits" not in str(old.value)
    assert NOTICE in notices(tmp_path / "abk.yaml")

    with pytest.raises(config.ConfigError, match=r"usage_limits\.session\.usage_pause_pct"):
        load_text(tmp_path, runtime_block("usage_limits", pct=150))
