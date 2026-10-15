"""The docs, the `abk-config` skill, the rule and the changelog say where an installation's
facts go and what keeps them out of a public repository (spec: consumer-facts-in-env,
scrub-check, stored-text-scrub, public-config-doctor)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIGURATION = ROOT / "docs" / "configuration.md"
CLI = ROOT / "docs" / "cli.md"
INIT = ROOT / "docs" / "init.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md"
AGENTS = ROOT / "AGENTS.md"
CHANGELOG = ROOT / "CHANGELOG.md"
CONFIG_AND_SKILL = [CONFIGURATION, SKILL]


def squashed(path: Path) -> str:
    return " ".join(path.read_text().split())


def section(path: Path, heading: str) -> str:
    """The text under the heading naming `heading`, to the next heading of its level or above."""
    text = path.read_text()
    match = re.search(rf"^(#+) .*{re.escape(heading)}.*$", text, re.M)
    assert match, f"{path.name} has no heading naming {heading}"
    rest = text[match.end() :]
    following = re.search(rf"^#{{1,{len(match[1])}}} ", rest, re.M)
    return " ".join((rest[: following.start()] if following else rest).split())


def unreleased_bullets() -> list[str]:
    text = CHANGELOG.read_text()
    start = text.index("## Unreleased") + 2
    following = re.search(r"^## ", text[start:], re.M)
    body = text[start : start + following.start()] if following else text[start:]
    return [" ".join(bullet.split()) for bullet in body.split("\n\n") if bullet.startswith("- ")]


@pytest.mark.parametrize("path", CONFIG_AND_SKILL, ids=lambda p: p.name)
def test_the_local_list_is_named(path: Path) -> None:
    assert "scrub.local" in squashed(path)


@pytest.mark.parametrize("path", CONFIG_AND_SKILL, ids=lambda p: p.name)
def test_a_verify_env_example_reads_from_the_env_file_with_generic_names(path: Path) -> None:
    text = path.read_text()
    assert re.search(r"verify:\s*\n\s+env:", text)
    assert re.search(r"from: env-file\b", text)
    assert re.search(r"file: \.env\b", text)


@pytest.mark.parametrize("path", CONFIG_AND_SKILL, ids=lambda p: p.name)
def test_the_overlay_is_named_with_a_worked_example(path: Path) -> None:
    text = path.read_text()
    assert "abk.local.yaml" in text
    assert re.search(r"abk\.local\.yaml[^`]*\n+```ya?ml\n", text)


@pytest.mark.parametrize("path", CONFIG_AND_SKILL, ids=lambda p: p.name)
def test_the_two_local_layers_are_told_apart(path: Path) -> None:
    text = squashed(path).lower()
    assert re.search(r"single values?.{0,80}secrets?|secrets?.{0,80}single values?", text)
    assert re.search(r"structured.{0,60}user-specific|user-specific.{0,60}structured", text)
    assert "independent" in text
    assert re.search(r"both (can|may) be used|may both be used|can both be used|use both", text)


@pytest.mark.parametrize("path", CONFIG_AND_SKILL, ids=lambda p: p.name)
def test_the_loader_reads_one_layer_for_a_values_content_and_one_for_the_entry(
    path: Path,
) -> None:
    text = squashed(path).lower()
    assert "the loader reads" in text
    assert "entry itself" in text
    assert "verify.env" in text


@pytest.mark.parametrize("path", CONFIG_AND_SKILL, ids=lambda p: p.name)
def test_the_tracked_file_of_a_public_repo_holds_no_facts_or_user_values(path: Path) -> None:
    text = squashed(path).lower()
    assert "public" in text
    assert "neither consumer facts nor user-specific values" in text


@pytest.mark.parametrize("path", CONFIG_AND_SKILL, ids=lambda p: p.name)
def test_a_planning_repo_that_plans_only_itself_needs_no_other_repo_entries(path: Path) -> None:
    assert "needs no other repo entries" in squashed(path)


def test_the_skills_doctor_table_has_a_public_content_row() -> None:
    rows = [line for line in SKILL.read_text().splitlines() if line.startswith("| public content")]
    assert len(rows) == 1
    assert "abk.local.yaml" in rows[0]
    assert "scrub.local" in rows[0]


def test_the_command_reference_documents_scrub_store() -> None:
    text = section(CLI, "abk scrub-store")
    assert "--apply" in text
    assert "dry run" in text.lower()
    assert "<home>/" in text
    assert "pre-redact" in text


def test_the_scrub_check_reference_lists_the_root_name_condition_and_the_local_list() -> None:
    text = section(CLI, "abk scrub-check")
    assert "scrub.local" in text
    assert re.search(r"root'?s? name|name of the planning root", text)
    assert re.search(r"not (the )?target|is the target|its own checkout", text)


def test_init_documents_where_stack_facts_and_the_overlay_go() -> None:
    text = squashed(INIT)
    assert ".env" in text
    assert "abk.local.yaml" in text
    assert "scrub.local" in text


def test_the_changelog_names_the_guidance_the_check_the_terms_and_the_store_pass() -> None:
    bullets = unreleased_bullets()
    assert any(".env" in b and "from: env-file" in b and "abk.local.yaml" in b for b in bullets)
    assert any("public content" in b and "abk.local.yaml" in b for b in bullets)
    assert any("scrub-check" in b and "scrub.local" in b for b in bullets)
    assert any("scrub-store" in b for b in bullets)


def test_the_rule_says_the_checkouts_own_entry_is_not_a_consumer_reference() -> None:
    text = section(AGENTS, "never names an installation")
    assert re.search(
        r"checkout'?s own entry in its own `abk\.yaml` is not a consumer reference", text
    )
