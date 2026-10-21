"""The documents and the skill say a unit parked on a held split can be requeued."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md"
REFUSED_STATES = ("running", "in review", "merged", "pull request")


def squashed(text: str) -> str:
    """The text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(text.replace("`", "").split())


def requeue_section() -> str:
    """`docs/cli.md`'s `abk requeue` section, up to the next heading."""
    text = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    start = text.index("### `abk requeue UNIT")
    body = text.index("\n", start)
    end = re.search(r"^#{1,3} ", text[body:], re.M)
    return squashed(text[start : body + end.start()] if end else text[start:])


def skill_text() -> str:
    return squashed(SKILL.read_text(encoding="utf-8"))


def assert_names_the_parked_rule(text: str, name: str) -> None:
    assert re.search(r"parked on (a )?(held )?(e2e-test )?split", text, re.I), name
    assert re.search(r"parked.{0,300}--rework|--rework.{0,300}parked", text, re.I), name
    assert "--restart" in text, name
    assert re.search(
        r"plain requeue.{0,200}(refused|is refused).{0,200}(held|release)", text, re.I
    ), f"{name} lacks the refusal of a plain requeue while the split is held"
    for state in REFUSED_STATES:
        assert state in text, f"{name} lacks the refusal that stays for {state}"


def test_the_cli_document_gives_the_parked_unit_rule() -> None:
    text = requeue_section()
    assert_names_the_parked_rule(text, "docs/cli.md")
    assert "a planned or merged one has nothing to retry" not in text
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("\n## ", 2)[1]
    assert len(re.findall(r"`--restart` now accept a unit parked on a held", unreleased)) == 1


def test_the_pipeline_skill_gives_the_parked_unit_rule() -> None:
    assert_names_the_parked_rule(skill_text(), "abk-pipeline skill")


def test_the_skill_split_held_paragraph_tells_a_person_what_to_do_for_a_mis_tagged_test() -> None:
    text = skill_text()
    start = text.index("Waiting for an e2e-test split")
    assert re.search(r"mis-?tagged.{0,300}--rework|--rework.{0,300}mis-?tagged", text[start:])


@pytest.mark.parametrize("document", ["README.md", "docs/architecture.md"])
def test_the_readme_and_architecture_say_a_parked_unit_can_be_requeued(document: str) -> None:
    text = squashed((ROOT / document).read_text(encoding="utf-8"))
    if document == "README.md":
        assert re.search(r"abk requeue UNIT[^|]*\|[^|]*\|[^|]*parked", text, re.I)
    else:
        assert re.search(r"parked.{0,400}requeue(d)? with --rework", text, re.I)
