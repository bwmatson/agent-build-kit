"""The limits example the documents and the skills show for the wait-end requeue loads."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.config import LimitsConfig, ProjectLimitsConfig

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
SETTING_DOCUMENTS = (
    ROOT / "docs" / "configuration.md",
    SKILLS / "abk-config" / "SKILL.md",
)
SETTING_IDS = ["configuration.md", "abk-config-skill"]


def block(path: Path, key: str) -> str:
    """The example's top-level `key:` block as raw text, up to the next unindented line."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"{key}:")
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i] and not lines[i][0].isspace()),
        len(lines),
    )
    return "\n".join(lines[start:end])


@pytest.mark.parametrize("path", SETTING_DOCUMENTS, ids=SETTING_IDS)
def test_the_setting_sits_in_the_global_limits_example_and_loads(path: Path) -> None:
    assert "wait_end_requeue:" not in block(path, "project_limits")
    loaded = yaml.safe_load(block(path, "global_limits"))["global_limits"]
    assert "wait_end_requeue" in loaded
    assert "wait_end_requeue" not in ProjectLimitsConfig.model_fields
    assert LimitsConfig.model_validate(loaded).wait_end_requeue.value == "auto"
