"""The documents and the skills describe the manual steps (spec: manual-steps)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
DECLARING = (
    ROOT / "docs" / "cli.md",
    ROOT / "docs" / "designs/unit-graph.md",
    SKILLS / "abk-authoring" / "SKILL.md",
)
DECLARING_IDS = ["cli.md", "designs/unit-graph.md", "abk-authoring-skill"]


def text(path: Path) -> str:
    return flat(path.read_text(encoding="utf-8").replace("`", ""))


@pytest.mark.parametrize("path", DECLARING, ids=DECLARING_IDS)
def test_when_to_declare_a_manual_step_is_given_with_its_runbook(path: Path) -> None:
    said = text(path)
    assert "Manual:" in said, path.name
    assert re.search(r"only a person can do", said, re.I), path.name
    assert re.search(r"Manual:.{0,600}runbook|runbook.{0,600}Manual:", said, re.I), path.name


def test_the_cli_document_lists_the_manual_commands() -> None:
    said = text(ROOT / "docs" / "cli.md")
    for command in ("abk manual list", "abk manual raise", "abk manual check"):
        assert command in said, command


def test_the_pipeline_skill_says_what_waiting_for_a_manual_step_means() -> None:
    said = text(SKILLS / "abk-pipeline" / "SKILL.md")
    assert "waiting for manual step" in said
    assert re.search(r"waiting for manual step.{0,600}abk manual list", said, re.I | re.S)


def test_the_needs_a_human_table_names_a_raised_manual_step_for_a_builder_limit() -> None:
    body = (SKILLS / "abk-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    section = body.split('## Why a unit is held "needs a human"', 1)[1].split("\n## ", 1)[0]
    assert re.search(r"abk manual raise", flat(section))


GUIDES = [SKILLS / "abk-pipeline" / "SKILL.md", SKILLS / "abk-authoring" / "SKILL.md"]


def squashed(path: Path) -> str:
    return " ".join(path.read_text().split())


def section(path: Path, heading: str) -> str:
    """The text under the heading naming `heading`, to the next heading of its level or above."""
    body = path.read_text()
    match = re.search(rf"^(#+) .*{re.escape(heading)}.*$", body, re.M | re.I)
    assert match, f"{path.name} has no heading naming {heading}"
    rest = body[match.end() :]
    following = re.search(rf"^#{{1,{len(match[1])}}} ", rest, re.M)
    return " ".join((rest[: following.start()] if following else rest).split())


def test_the_cli_document_describes_manual_done_and_its_refusals() -> None:
    said = section(ROOT / "docs" / "cli.md", "abk manual")

    assert "abk manual done" in said
    assert "--note" in said and "--unit" in said
    assert "abk manual check" in said, "it does not say a step with a check is refused"
    assert re.search(r"unknown", said, re.I), "it does not say an unknown slug is refused"
    assert re.search(r"two|more than one|ambiguous", said, re.I), "no word on a shared slug"
    assert re.search(r"already done", said, re.I), "it does not say what a done step does"


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.parent.name)
def test_a_guide_says_what_a_check_runs_with(path: Path) -> None:
    said = squashed(path)

    assert "PATH" in said and "LANG" in said, "it does not name the whole environment"
    assert re.search(r"only `?PATH`? and `?LANG`?|`?PATH`? and `?LANG`? only", said)
    assert re.search(r"worktree", said), "it does not name the directory a check runs in"
    assert re.search(r"checkout", said), "it does not name the checkout as the other directory"


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.parent.name)
def test_a_guide_says_when_to_write_a_check_and_when_to_attest(path: Path) -> None:
    said = squashed(path)

    assert "abk manual done" in said
    assert re.search(r"attest", said, re.I), "it does not use the word attest"
    assert re.search(r"only a person can", said, re.I), "it does not say attesting is for a person"
