"""The documents, the `abk-config` skill and the changelog say how usage is estimated: recorded cost
times a learned points-per-dollar figure where the cost basis is adopted, the flat per-unit figure
otherwise (spec: usage-pause, the estimate adds recorded cost)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from agent_build_kit.config import ClaudeLimitsConfig

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATION = ROOT / "docs" / "configuration.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md"
ARCHITECTURE = ROOT / "docs" / "architecture.md"
CLI = ROOT / "docs" / "cli.md"
DEFAULTS = {
    "usage_estimate_basis": "cost",
    "usage_estimate_intercept": "",
    "usage_cost_min_pairs": "8",
    "usage_cost_quantile": "0.9",
}
FROM_NOTHING_BUT_UNITS = re.compile(
    r"(derived|calibrated|taken) (from|over) nothing but|only from (the )?units|from units alone",
    re.IGNORECASE,
)


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def usage_paragraph() -> str:
    text = ARCHITECTURE.read_text()
    start = text.index("**The usage guard**")
    return flat(text[start : start + 9000])


def unreleased_bullets() -> list[str]:
    changelog = (ROOT / "CHANGELOG.md").read_text()
    section = re.split(r"^## ", changelog, flags=re.MULTILINE)[1]
    return [flat(b) for b in re.split(r"\n\s*\n", section) if b.lstrip().startswith("- ")]


@pytest.mark.parametrize("path", [CONFIGURATION, SKILL], ids=["configuration", "abk-config skill"])
@pytest.mark.parametrize("name", list(DEFAULTS))
def test_the_limits_documentation_names_each_setting_with_its_default(
    path: Path, name: str
) -> None:
    lines = [line for line in path.read_text().splitlines() if name in line]

    assert lines, f"{path.name} does not name {name}"
    assert DEFAULTS[name] in " ".join(lines)


def test_the_intercept_default_differs_by_window_in_the_documents() -> None:
    for path in (CONFIGURATION, SKILL):
        text = flat(path.read_text())
        assert re.search(r"usage_estimate_intercept.{0,200}(session|week)", text), path.name


def test_the_architecture_document_says_the_estimate_adds_recorded_cost() -> None:
    text = usage_paragraph()

    assert re.search(r"recorded cost.{0,120}points.per.dollar", text, re.IGNORECASE)
    assert re.search(r"(no unit|unit-less|without a unit)", text, re.IGNORECASE)
    assert re.search(r"flat.{0,60}(per-unit )?allowance", text, re.IGNORECASE)
    assert "plus an allowance for each unit" not in text


def test_the_cli_document_describes_the_allowances_line_and_the_replay_lines() -> None:
    text = flat(CLI.read_text())

    assert re.search(r"points/\$", text)
    assert "pairs with cost" in text
    assert re.search(r"usage replay.{0,1500}\bflat\b.{0,300}\bcost\b", text, re.IGNORECASE)
    assert "cost_estimate" in text
    assert re.search(r"spent from \$\d+\.\d\d recorded", text)
    assert re.search(r"not yet recorded", text)
    status = text[text.index("### `abk status`") :]
    assert "usage allowances:" in status[:3000]


@pytest.mark.parametrize("path", [CONFIGURATION, SKILL, ARCHITECTURE, CLI], ids=lambda p: p.name)
def test_no_document_says_the_allowance_comes_from_nothing_but_units(path: Path) -> None:
    assert not FROM_NOTHING_BUT_UNITS.search(flat(path.read_text()))


def test_the_changelog_has_one_bullet_for_the_estimate_under_unreleased() -> None:
    bullets = [b for b in unreleased_bullets() if "usage_estimate_basis" in b]

    assert len(bullets) == 1
    assert "pipeline overhead" in bullets[0]
    assert (ROOT / "CHANGELOG.md").read_text().count("usage_estimate_basis") == 1


def limits_block(path: Path) -> dict:
    """The `limits:` mapping of the abk.yaml example in a document, parsed."""
    lines = path.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip().startswith("limits:"))
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
    return yaml.safe_load("\n".join(block))["limits"]


@pytest.mark.parametrize("path", [CONFIGURATION, SKILL], ids=["configuration", "abk-config skill"])
def test_the_documented_limits_block_is_valid_and_places_the_estimate_keys_per_window(
    path: Path,
) -> None:
    limits = ClaudeLimitsConfig.model_validate(limits_block(path))

    assert limits.session.usage_estimate_basis == "cost"
    assert limits.session.usage_estimate_intercept is True
    assert limits.weekly.usage_estimate_basis == "cost"
    assert limits.weekly.usage_estimate_intercept is False
