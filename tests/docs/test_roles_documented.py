"""The documents and the `abk-config` skill say what a role affects (spec: roles)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.role_names import ROLES

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = [
    ROOT / "docs" / "configuration.md",
    ROOT / "docs" / "agent-runtimes.md",
    ROOT / "src" / "agent_build_kit" / "skills" / "abk-config" / "SKILL.md",
]
HEADING = re.compile(r"^#+ .*what a role affects.*$", re.IGNORECASE | re.MULTILINE)
EFFECTS = [
    "The ledger label",
    "Telemetry",
    "The usage forecast",
    "The model",
    "Session reuse",
]


def section(path: Path) -> str:
    """The text from the document's 'what a role affects' heading to the next heading of the same
    or a higher level."""
    text = path.read_text()
    match = HEADING.search(text)
    assert match, f"{path.name} has no heading saying what a role affects"
    level = len(match.group(0)) - len(match.group(0).lstrip("#"))
    rest = text[match.end() :]
    end = re.search(rf"^#{{1,{level}}} ", rest, re.MULTILINE)
    return re.sub(r"\s+", " ", rest[: end.start()] if end else rest)


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
def test_the_section_names_every_role(path: Path) -> None:
    text = section(path)

    missing = [role for role in ROLES if not re.search(rf"\b{role}\b", text)]
    assert not missing, f"{path.name} does not name the roles {missing}"


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
@pytest.mark.parametrize("effect", EFFECTS)
def test_the_section_says_what_a_role_affects(path: Path, effect: str) -> None:
    assert f"**{effect}.**" in section(path), f"{path.name} has no bullet for {effect}"


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
def test_the_section_says_restack_continues_its_own_session(path: Path) -> None:
    text = section(path)

    assert re.search(r"\brestack\b.{0,80}continues its own session", text)
    assert re.search(r"\bregression\b.{0,40}\bplan\b.{0,40}\blogin_refresh\b.{0,40}never", text)


@pytest.mark.parametrize("path", DOCUMENTS, ids=lambda path: path.name)
def test_the_section_says_which_roles_build_and_review_cover(path: Path) -> None:
    text = section(path)

    assert re.search(r"\bbuild\b.{0,120}\bimplement\b.{0,40}\brework\b", text)
    assert re.search(
        r"\breview\b.{0,120}\brework_review\b|\brework_review\b.{0,120}\breview\b", text
    )
