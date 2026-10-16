"""The kit's own splits are documented as an installation's configuration (spec: tier2-splits)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

from agent_build_kit.config import WorkspaceConfig

ROOT = Path(__file__).resolve().parent.parent


def documented_block() -> dict:
    text = (ROOT / "docs" / "agent-runtimes.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```ya?ml\n(.*?)```", text, re.DOTALL)
    found = [yaml.safe_load(block) for block in blocks if "tier2_splits:" in block]
    assert len(found) == 1, "docs/agent-runtimes.md needs one tests.tier2_splits example block"
    return found[0]


def registered_markers() -> set[str]:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = project["tool"]["pytest"]["ini_options"]["markers"]
    return {line.split(":", 1)[0] for line in declared if line.startswith("runtime_")}


def test_the_documented_example_loads_and_gives_a_split_to_each_registered_runtime_marker() -> None:
    loaded = WorkspaceConfig.model_validate(documented_block())

    splits = loaded.tests.tier2_splits
    assert {entry.marker for entry in splits.values()} == registered_markers()
    assert set(splits) >= {"acp", "claude_code"}
