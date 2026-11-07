"""Every role has a configurable model (spec: roles).

The model config is a mapping from a role to a model, read by the role's name, and one defaults
table gives every role its model. Roles are named by string here: the enum's members are strings,
so a test names a role the way `abk.yaml` does."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_build_kit import config, runtimes
from agent_build_kit.config import DEFAULT_MODELS, ConfigError, ModelsConfig, RuntimeModelsConfig
from agent_build_kit.runtimes.claude_code import refresh_login
from agent_build_kit.settings import Settings
from tests.call_rows import agent_rows
from tests.conftest import make_installation
from tests.role_names import ROLES
from tests.runtimes.selectable import SelectableRuntime, select


def activate(root: Path, text: str) -> config.WorkspaceConfig:
    path = root / "abk.yaml"
    path.write_text(text)
    loaded = config.load(path)
    config.activate(loaded, root)
    return loaded


def test_every_role_has_a_default_model_in_the_one_table() -> None:
    assert set(DEFAULT_MODELS) == set(ROLES)


def test_the_defaults_table_names_opus_sonnet_and_the_cheap_model() -> None:
    assert {role: DEFAULT_MODELS[role] for role in ROLES} == {
        "implement": "sonnet",
        "rework": "sonnet",
        "review": "opus",
        "rework_review": "opus",
        "regression": "opus",
        "plan": "opus",
        "restack": "haiku",
        "login_refresh": "haiku",
    }


@pytest.mark.parametrize("role", ROLES)
def test_nothing_set_resolves_every_role_to_the_runtime_s_default(
    tmp_path: Path, role: str
) -> None:
    activate(tmp_path, "version: 1\n")

    assert config.models()[role] == runtimes.active().default_models[role] == DEFAULT_MODELS[role]


@pytest.mark.parametrize("role", ROLES)
def test_the_flat_block_sets_any_role(tmp_path: Path, role: str) -> None:
    activate(tmp_path, f"version: 1\nmodels:\n  {role}: flat-model\n")

    assert config.models()[role] == "flat-model"


@pytest.mark.parametrize("role", ROLES)
def test_a_runtime_s_own_block_sets_any_role(tmp_path: Path, role: str) -> None:
    loaded = activate(
        tmp_path,
        f"version: 1\nmodels:\n  {role}: flat-model\n"
        f"runtimes:\n  claude_code:\n    models:\n      {role}: own-model\n",
    )

    assert loaded.runtimes["claude_code"].models[role] == "own-model"
    assert config.models()[role] == "own-model"


@pytest.mark.parametrize("role", ROLES)
def test_a_role_left_out_takes_the_active_runtime_s_default(tmp_path: Path, role: str) -> None:
    other = next(name for name in ROLES if name != role)
    activate(tmp_path, f"version: 1\nmodels:\n  {other}: flat-model\n")

    assert config.models()[role] == runtimes.active().default_models[role]


def test_another_runtime_s_block_is_not_sent_to_the_active_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("other"))
    activate(
        tmp_path,
        "version: 1\nruntime: claude_code\n"
        "runtimes:\n  other:\n    models:\n      restack: other-model\n",
    )

    assert config.models()["restack"] == runtimes.get("claude_code").default_models["restack"]


@pytest.mark.parametrize("scope", ["models", "runtimes"])
def test_an_unknown_key_is_refused_naming_the_roles(tmp_path: Path, scope: str) -> None:
    text = (
        "version: 1\nmodels:\n  not_a_role: x\n"
        if scope == "models"
        else "version: 1\nruntimes:\n  claude_code:\n    models:\n      not_a_role: x\n"
    )

    with pytest.raises((ConfigError, ValueError)) as refused:
        activate(tmp_path, text)

    message = str(refused.value)
    assert "not_a_role" in message
    assert all(role in message for role in ROLES)


def test_a_file_with_the_old_keys_loads_unchanged(tmp_path: Path) -> None:
    activate(
        tmp_path,
        "version: 1\nmodels:\n  implement: a\n  rework: b\n  review: c\n  rework_review: d\n"
        "  regression: e\n  plan: f\n",
    )

    resolved = config.models()
    assert [resolved[role] for role in ROLES[:6]] == ["a", "b", "c", "d", "e", "f"]


def test_login_refresh_asks_for_the_model_the_table_gives_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installation = make_installation(tmp_path, models={"login_refresh": "chosen-model"})
    asked: list[list[str]] = []

    def run(argv, **kwargs) -> subprocess.CompletedProcess[str]:
        asked.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    refresh_login(run=run)

    (argv,) = asked
    assert argv[argv.index("--model") + 1] == "chosen-model"
    (row,) = agent_rows(installation)
    assert row["model"] == "chosen-model"


def test_login_refresh_defaults_to_the_table_s_model(tmp_path: Path) -> None:
    installation = make_installation(tmp_path)
    asked: list[list[str]] = []

    def run(argv, **kwargs) -> subprocess.CompletedProcess[str]:
        asked.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    refresh_login(run=run)

    (argv,) = asked
    assert argv[argv.index("--model") + 1] == DEFAULT_MODELS["login_refresh"]
    assert agent_rows(installation)[0]["model"] == DEFAULT_MODELS["login_refresh"]


@pytest.mark.parametrize("role", ROLES)
def test_the_machine_override_wins_over_the_runtime_block_and_the_flat_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, role: str
) -> None:
    monkeypatch.setenv(f"ABK_{role.upper()}_MODEL", "machine-model")
    monkeypatch.setattr("agent_build_kit.settings.settings", Settings(_env_file=None))
    activate(
        tmp_path,
        f"version: 1\nmodels:\n  {role}: flat-model\n"
        f"runtimes:\n  claude_code:\n    models:\n      {role}: own-model\n",
    )

    assert config.models()[role] == "machine-model"


def test_a_name_that_is_not_a_role_is_a_key_error(tmp_path: Path) -> None:
    activate(tmp_path, "version: 1\n")

    with pytest.raises(KeyError):
        config.models()["model_dump"]
    with pytest.raises(KeyError):
        config.runtime_entry().models["model_dump"]


def test_the_defaults_table_and_the_role_type_name_the_same_roles() -> None:
    assert set(DEFAULT_MODELS) == set(ROLES)
    assert set(ModelsConfig.model_fields) == set(ROLES)
    assert set(RuntimeModelsConfig.model_fields) == set(ROLES)
    assert all(f"{role}_model" in Settings.model_fields for role in ROLES)


def test_login_refresh_uses_the_claude_code_model_whatever_the_active_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blank = ModelsConfig(**{role: "" for role in DEFAULT_MODELS})
    select(monkeypatch, SelectableRuntime("other", default_models=blank))
    make_installation(tmp_path, runtime="other")
    asked: list[list[str]] = []

    def run(argv, **kwargs) -> subprocess.CompletedProcess[str]:
        asked.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    refresh_login(run=run)

    (argv,) = asked
    assert argv[argv.index("--model") + 1] == "haiku"
