"""`global_limits` is the workspace-wide block; `runtimes.<name>.limits` keeps its name."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import config
from agent_build_kit.config import LimitsConfig


def load_text(tmp_path: Path, text: str) -> config.WorkspaceConfig:
    path = tmp_path / "abk.yaml"
    path.write_text(text)
    return config.load(path)


def test_a_setting_under_its_new_name_is_read_and_the_rest_default(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, "version: 1\nglobal_limits:\n  max_review_rounds: 5\n")

    block = loaded.global_limits
    assert block.max_review_rounds == 5
    assert block == LimitsConfig(max_review_rounds=5)


def test_the_effective_config_prints_global_limits_and_no_root_limits_key(tmp_path: Path) -> None:
    loaded = load_text(tmp_path, "version: 1\nglobal_limits:\n  max_review_rounds: 5\n")

    shown = config.dump(loaded)

    assert "global_limits:" in shown
    assert not any(line.startswith("limits:") for line in shown.splitlines())


def test_the_runtime_s_usage_thresholds_keep_their_name_and_report_no_deprecation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(
        "version: 1\nruntimes:\n  claude_code:\n    usage_limits:\n      usage_cache_minutes: 7\n"
    )

    loaded = config.load(path)

    assert loaded.runtimes["claude_code"].usage_limits.usage_cache_minutes == 7
    assert config.deprecations(path) == []
