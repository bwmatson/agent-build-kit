"""The documents and skills describe e2e-test splits, holds and `abk e2e-test check`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.profiles.python_uv import PythonUvProfile

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
SKILL_NAMES = ("abk-config", "abk-authoring", "abk-pipeline")
# Spelled in two halves so the file carries no old spelling.
OLD_NAMES = ("runtimes_blocked", "runtimes_allowed", "tier" + "2_runtimes")


def squashed(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def command_entry() -> str:
    """The command document from the first mention of `abk e2e-test check` to the next heading."""
    text = (DOCS / "cli.md").read_text(encoding="utf-8")
    check = "abk e2e-test check"
    assert check in text, f"docs/cli.md has no entry for `{check}`"
    start = text.index(check)
    following = re.search(r"^#{1,3} ", text[start:], re.M)
    return " ".join(text[start : start + following.start()].split()) if following else text[start:]


@pytest.mark.parametrize("name", ["e2e_splits", "marker", "hold", "rest", "e2e-held.json"])
def test_the_configuration_document_names_the_split_setting(name: str) -> None:
    assert f"`{name}`" in squashed(DOCS / "configuration.md")


def test_the_configuration_document_describes_the_repo_override() -> None:
    text = squashed(DOCS / "configuration.md")
    assert re.search(r"under a repo's own `?tests`?[^.]*replaces", text)
    blocks = re.findall(
        r"```ya?ml\n(.*?)```", (DOCS / "configuration.md").read_text(encoding="utf-8"), re.S
    )
    assert any("repos:" in block and "e2e_splits" in block for block in blocks)


def test_the_command_document_gives_the_check_and_its_exit_codes() -> None:
    assert re.search(r"exit", command_entry(), re.I)


def test_the_runtimes_document_names_the_exclusive_membership_rule() -> None:
    text = squashed(DOCS / "agent-runtimes.md")
    assert re.search(r"at most one split|exactly one split|one split only|exclusive", text, re.I)


@pytest.mark.parametrize("kind", PythonUvProfile.selector_kinds)
def test_the_runtimes_document_names_each_selector_kind_of_the_profile(kind: str) -> None:
    text = squashed(DOCS / "agent-runtimes.md")
    assert re.search(rf"selector kinds?[^.]*`{kind}`", text, re.I)


def test_no_document_names_the_old_runtime_lists_once_the_splits_are_documented() -> None:
    assert "`e2e_splits`" in squashed(DOCS / "configuration.md")
    paths = [*DOCS.glob("*.md"), ROOT / "README.md", *SKILLS.glob("*/SKILL.md")]
    offenders = [
        (p.name, old) for p in paths for old in OLD_NAMES if old in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


@pytest.mark.parametrize("skill", SKILL_NAMES)
def test_each_skill_names_the_check(skill: str) -> None:
    assert "abk e2e-test check" in squashed(SKILLS / skill / "SKILL.md")
