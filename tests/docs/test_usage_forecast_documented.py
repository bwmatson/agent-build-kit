"""The documents and the `abk-config` skill describe the per-tier usage forecast: its three
settings, `abk report --by tier`, and the forecast beside the estimate (spec: usage-pause,
usage-accounting, usage-reporting)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = ROOT / "docs" / "configuration.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
CLI = ROOT / "docs" / "cli.md"
SETTINGS = ["usage_forecast", "usage_forecast_min_runs", "usage_forecast_quantile"]


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


@pytest.mark.parametrize("path", [CONFIGURATION, SKILL], ids=["configuration", "abk-config skill"])
@pytest.mark.parametrize("name", SETTINGS)
def test_the_settings_documentation_names_each_forecast_setting(path: Path, name: str) -> None:
    lines = [line for line in path.read_text().splitlines() if re.search(rf"{name}\b", line)]

    assert lines, f"{path.name} does not name {name}"


def test_the_cli_document_describes_the_report_by_tier() -> None:
    text = flat(CLI.read_text())

    assert re.search(r"abk report.{0,200}--by tier", text)
    assert re.search(r"--by tier.{0,600}forecast", text, re.IGNORECASE)


def test_the_architecture_document_describes_the_forecast_where_the_estimate_is() -> None:
    text = flat(ARCHITECTURE.read_text())
    start = text.index("**The usage guard**")
    paragraph = text[start : start + 12000]

    assert re.search(r"forecast", paragraph, re.IGNORECASE)
    assert re.search(r"forecast.{0,400}tier|tier.{0,400}forecast", paragraph, re.IGNORECASE)
    assert "usage_forecast" in paragraph
