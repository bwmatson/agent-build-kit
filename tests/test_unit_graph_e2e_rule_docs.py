"""The rule for when a step is e2e is written where authors read it: the unit-graph document
and the authoring skill (spec: sandbox-e2e-policy)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import skills

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = Path(skills.SKILLS_DIR).parent
DOCUMENTS = {
    "docs/unit-graph.md": ROOT / "docs" / "unit-graph.md",
    "abk-authoring skill": PACKAGE / "skills" / "abk-authoring" / "SKILL.md",
}


def words(path: Path) -> str:
    return " ".join(path.read_text().lower().split())


@pytest.mark.parametrize("name", DOCUMENTS)
def test_e2e_is_the_step_that_needs_something_running(name: str) -> None:
    text = words(DOCUMENTS[name])

    assert "needs a running service" in text or "needs something running" in text


@pytest.mark.parametrize("name", DOCUMENTS)
def test_integration_is_across_modules_of_one_package_and_needs_nothing_running(
    name: str,
) -> None:
    text = words(DOCUMENTS[name])

    assert "needs nothing running" in text
    assert "modules of one package" in text


@pytest.mark.parametrize("name", DOCUMENTS)
def test_a_refused_loopback_connection_is_the_sign_to_tag_e2e(name: str) -> None:
    text = words(DOCUMENTS[name])

    assert "localhost" in text or "loopback" in text
    assert "[e2e-test]" in text
