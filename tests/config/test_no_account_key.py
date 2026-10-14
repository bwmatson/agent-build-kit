"""The account is a fact of the machine, not of the workspace: abk.yaml has no key for it
(spec: claude-account)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import ConfigError, RuntimeConfig, WorkspaceConfig, load

KEYS = ("claude_home", "config_dir", "claude_config_dir")

UNDER_ROOT = "repos: {{}}\n{key}: /accounts/a\n"
UNDER_RUNTIME = "repos: {{}}\nruntimes:\n  claude_code:\n    {key}: /accounts/a\n"


@pytest.mark.parametrize("model", [WorkspaceConfig, RuntimeConfig])
def test_no_field_names_the_account(model: type[WorkspaceConfig] | type[RuntimeConfig]) -> None:
    assert not set(KEYS) & set(model.model_fields)


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("template", [UNDER_ROOT, UNDER_RUNTIME], ids=["root", "runtime"])
def test_an_abk_yaml_with_the_key_fails_to_load_naming_it(
    tmp_path: Path, key: str, template: str
) -> None:
    path = tmp_path / "abk.yaml"
    path.write_text(template.format(key=key))

    with pytest.raises(ConfigError, match=key):
        load(path)
