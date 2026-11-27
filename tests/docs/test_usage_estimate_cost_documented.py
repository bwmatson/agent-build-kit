"""The limits example the documents and the `abk-config` skill show loads through the settings model
and places the usage estimate keys per window (spec: usage-pause, the estimate adds recorded
cost)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent_build_kit.config import ClaudeLimitsConfig

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = ROOT / "docs" / "configuration.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md"


def limits_block(path: Path) -> dict:
    """The `usage_limits:` mapping of the abk.yaml example in a document, parsed."""
    lines = path.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("usage_limits:"))
    indent = len(lines[start]) - len(lines[start].lstrip())
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if (
            line.strip()
            and len(line) - len(line.lstrip()) <= indent
            and not line.strip().startswith("#")
        ):
            break
        block.append(line)
    return yaml.safe_load("\n".join(block))["usage_limits"]


@pytest.mark.parametrize("path", [CONFIGURATION, SKILL], ids=["configuration", "abk-config skill"])
def test_the_documented_limits_block_is_valid_and_places_the_estimate_keys_per_window(
    path: Path,
) -> None:
    limits = ClaudeLimitsConfig.model_validate(limits_block(path))

    assert limits.session.usage_estimate_basis == "cost"
    assert limits.session.usage_estimate_intercept is True
    assert limits.weekly.usage_estimate_basis == "cost"
    assert limits.weekly.usage_estimate_intercept is False
