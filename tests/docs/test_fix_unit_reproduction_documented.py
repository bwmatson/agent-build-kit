"""The documents and the changelog describe the reproduction check a fix unit makes before its
first build (spec: fix-unit-reproduction)."""

from __future__ import annotations

from pathlib import Path

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
CONFIGURATION = (ROOT / "docs" / "configuration.md").read_text()
SKILL = (ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md").read_text()


def unreleased() -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    return text[text.index("## Unreleased") :].split("\n## ", 1)[0]


def test_the_architecture_names_the_check_and_its_three_outcomes() -> None:
    assert "fix_reproduction_runs" in ARCHITECTURE
    assert "`reproduce`" in ARCHITECTURE, "the node between prepare and tests"
    assert "alone and under load" in ARCHITECTURE
    assert "no longer in the tree" in ARCHITECTURE, "the test is gone: satisfied"
    assert "merged since" in ARCHITECTURE, "the test was fixed elsewhere: satisfied"
    assert "not reproduced" in ARCHITECTURE and "needs_human" in ARCHITECTURE
    assert "abk requeue --restart --note" in ARCHITECTURE and "abk retire" in ARCHITECTURE


def test_the_architecture_says_which_units_are_not_checked() -> None:
    for skipped in ("rework", "product-defect", "restart"):
        assert skipped in ARCHITECTURE


def test_the_configuration_document_and_the_config_skill_list_the_setting() -> None:
    for text in (CONFIGURATION, SKILL):
        assert "fix_reproduction_runs: 5" in text
        assert "(0: off)" in text.split("fix_reproduction_runs: 5", 1)[1].splitlines()[0]


def test_the_changelog_has_one_bullet_for_it() -> None:
    bullets = [b for b in unreleased().split("\n- ") if "fix_reproduction_runs" in b]
    assert len(bullets) == 1
