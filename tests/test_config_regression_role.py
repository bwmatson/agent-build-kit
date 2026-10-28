"""The `regression` model role: the model the regression agent runs on.

It resolves like the other roles: this machine's `ABK_REGRESSION_MODEL`, then the runtime's own
`runtimes.<name>.models.regression`, then the flat `models.regression`, then the runtime's
default. Every runtime has a default, Claude Code's is Opus, and `global_limits` takes a cap on
regression-agent runs per hour (spec: regression-agent)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import config, runtimes
from agent_build_kit.config import ConfigError, ModelsConfig
from agent_build_kit.settings import Settings, settings
from tests.runtimes.selectable import SelectableRuntime, select


def activate(root: Path, text: str) -> config.WorkspaceConfig:
    path = root / "abk.yaml"
    path.write_text(text)
    loaded = config.load(path)
    config.activate(loaded, root)
    return loaded


def test_the_flat_block_takes_a_regression_role(tmp_path: Path) -> None:
    activate(tmp_path, "version: 1\nmodels:\n  regression: haiku\n")

    assert config.models().regression == "haiku"


def test_a_runtime_s_own_block_takes_a_regression_role(tmp_path: Path) -> None:
    loaded = activate(
        tmp_path,
        "version: 1\nruntimes:\n  claude_code:\n    models:\n      regression: sonnet\n",
    )

    assert loaded.runtimes["claude_code"].models.regression == "sonnet"
    assert config.models().regression == "sonnet"


def test_the_runtime_s_block_wins_over_the_flat_block(tmp_path: Path) -> None:
    activate(
        tmp_path,
        "version: 1\nmodels:\n  regression: haiku\n"
        "runtimes:\n  claude_code:\n    models:\n      regression: sonnet\n",
    )

    assert config.models().regression == "sonnet"


def test_a_role_left_out_takes_the_runtime_s_default(tmp_path: Path) -> None:
    activate(tmp_path, "version: 1\nmodels:\n  implement: haiku\n")

    assert config.models().regression == runtimes.active().default_models.regression


def test_another_runtime_s_regression_model_is_not_sent_to_the_active_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(monkeypatch, SelectableRuntime("other"))
    activate(
        tmp_path,
        "version: 1\nruntime: claude_code\n"
        "runtimes:\n  other:\n    models:\n      regression: other-regressor\n",
    )

    assert config.models().regression == runtimes.get("claude_code").default_models.regression


def test_the_machine_setting_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(
        tmp_path,
        "version: 1\nmodels:\n  regression: haiku\n"
        "runtimes:\n  claude_code:\n    models:\n      regression: sonnet\n",
    )
    monkeypatch.setattr(settings, "regression_model", "this-machine")

    assert config.models().regression == "this-machine"


def test_abk_regression_model_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ABK_REGRESSION_MODEL", "from-env")

    assert Settings().regression_model == "from-env"


def test_every_runtime_has_a_regression_default() -> None:
    for name in runtimes.names():
        default = runtimes.get(name).default_models

        assert isinstance(default, ModelsConfig)
        assert isinstance(default.regression, str), name


def test_claude_code_s_regression_default_is_opus() -> None:
    assert runtimes.get("claude_code").default_models.regression == "opus"


def test_global_limits_take_a_cap_on_regression_runs_per_hour(tmp_path: Path) -> None:
    named = activate(tmp_path, "version: 1\nglobal_limits:\n  max_regression_runs_per_hour: 3\n")
    left_out = activate(tmp_path, "version: 1\n")

    assert named.global_limits.max_regression_runs_per_hour == 3
    assert left_out.global_limits.max_regression_runs_per_hour == 10


def test_a_cap_of_zero_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        activate(tmp_path, "version: 1\nglobal_limits:\n  max_regression_runs_per_hour: 0\n")
