"""The `plan` model role: the model the planner's graph call runs on.

It resolves like the other roles: this machine's `ABK_PLAN_MODEL`, then the runtime's own
`runtimes.<name>.models.plan`, then the flat `models.plan`, then the runtime's default, which for
Claude Code is Opus (spec: planner-model, the planner has a model role)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config, runtimes
from agent_build_kit.config import ModelsConfig
from agent_build_kit.settings import Settings, settings
from tests.runtimes.selectable import SelectableRuntime, select


def activate(root: Path, text: str) -> config.WorkspaceConfig:
    path = root / "abk.yaml"
    path.write_text(text)
    loaded = config.load(path)
    config.activate(loaded, root)
    return loaded


def test_the_plan_role_defaults_to_opus() -> None:
    assert ModelsConfig().plan == "opus"


def test_nothing_set_resolves_to_opus_under_claude_code(tmp_path: Path) -> None:
    activate(tmp_path, "version: 1\n")

    assert config.models().plan == "opus"


def test_the_flat_block_takes_a_plan_role(tmp_path: Path) -> None:
    activate(tmp_path, "version: 1\nmodels:\n  plan: haiku\n")

    assert config.models().plan == "haiku"


def test_a_runtime_s_own_block_takes_a_plan_role(tmp_path: Path) -> None:
    loaded = activate(
        tmp_path,
        "version: 1\nruntimes:\n  claude_code:\n    models:\n      plan: sonnet\n",
    )

    assert loaded.runtimes["claude_code"].models.plan == "sonnet"
    assert config.models().plan == "sonnet"


def test_the_runtime_s_block_wins_over_the_flat_block(tmp_path: Path) -> None:
    activate(
        tmp_path,
        "version: 1\nmodels:\n  plan: haiku\n"
        "runtimes:\n  claude_code:\n    models:\n      plan: sonnet\n",
    )

    assert config.models().plan == "sonnet"


def test_a_role_left_out_takes_the_runtime_s_default(tmp_path: Path) -> None:
    activate(tmp_path, "version: 1\nmodels:\n  implement: haiku\n")

    assert config.models().plan == runtimes.active().default_models.plan == "opus"


def test_another_runtime_s_plan_model_is_not_sent_to_the_active_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("other"))
    activate(
        tmp_path,
        "version: 1\nruntime: claude_code\n"
        "runtimes:\n  other:\n    models:\n      plan: other-planner\n",
    )

    assert config.models().plan == runtimes.get("claude_code").default_models.plan == "opus"


def test_the_machine_setting_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(
        tmp_path,
        "version: 1\nmodels:\n  plan: haiku\n"
        "runtimes:\n  claude_code:\n    models:\n      plan: sonnet\n",
    )
    monkeypatch.setattr(settings, "plan_model", "this-machine")

    assert config.models().plan == "this-machine"


def test_abk_plan_model_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABK_PLAN_MODEL", "from-env")

    assert Settings().plan_model == "from-env"  # pyrefly: ignore[missing-attribute]


def test_claude_code_s_plan_default_is_opus() -> None:
    assert runtimes.get("claude_code").default_models.plan == "opus"


def test_a_runtime_with_no_names_of_its_own_names_no_planner_model() -> None:
    """An empty name means the agent's own default, so a table that selects nothing for the
    other roles selects nothing for this one."""
    assert runtimes.get("acp").default_models.plan == ""
