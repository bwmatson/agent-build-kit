"""The documents say how a manual step is attested and what a check runs with
(spec: manual-steps)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "docs" / "cli.md"
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
PIPELINE_GUIDE = SKILLS / "abk-pipeline" / "SKILL.md"
AUTHORING = SKILLS / "abk-authoring" / "SKILL.md"
GUIDES = [PIPELINE_GUIDE, AUTHORING]


def squashed(path: Path) -> str:
    return " ".join(path.read_text().split())


def section(path: Path, heading: str) -> str:
    """The text under the heading naming `heading`, to the next heading of its level or above."""
    text = path.read_text()
    match = re.search(rf"^(#+) .*{re.escape(heading)}.*$", text, re.M | re.I)
    assert match, f"{path.name} has no heading naming {heading}"
    rest = text[match.end() :]
    following = re.search(rf"^#{{1,{len(match[1])}}} ", rest, re.M)
    return " ".join((rest[: following.start()] if following else rest).split())


def test_the_cli_document_describes_manual_done_and_its_refusals() -> None:
    text = section(CLI, "abk manual")

    assert "abk manual done" in text
    assert "--note" in text and "--unit" in text
    assert "abk manual check" in text, "it does not say a step with a check is refused"
    assert re.search(r"unknown", text, re.I), "it does not say an unknown slug is refused"
    assert re.search(r"two|more than one|ambiguous", text, re.I), "no word on a shared slug"
    assert re.search(r"already done", text, re.I), "it does not say what a done step does"


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.parent.name)
def test_a_guide_says_what_a_check_runs_with(path: Path) -> None:
    text = squashed(path)

    assert "PATH" in text and "LANG" in text, "it does not name the whole environment"
    assert re.search(r"only `?PATH`? and `?LANG`?|`?PATH`? and `?LANG`? only", text)
    assert re.search(r"worktree", text), "it does not name the directory a check runs in"
    assert re.search(r"checkout", text), "it does not name the checkout as the other directory"


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.parent.name)
def test_a_guide_says_when_to_write_a_check_and_when_to_attest(path: Path) -> None:
    text = squashed(path)

    assert "abk manual done" in text
    assert re.search(r"attest", text, re.I), "it does not use the word attest"
    assert re.search(r"only a person can", text, re.I), "it does not say attesting is for a person"
