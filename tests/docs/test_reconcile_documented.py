"""The documents and the skill describe the reconcile pass and `abk reconcile`."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md"


def squashed(text: str) -> str:
    """The text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(text.replace("`", "").split())


def poller_section() -> str:
    """`docs/architecture.md`'s "Polling and events" section, up to the next heading."""
    text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    start = text.index("### 4. Polling and events")
    body = text.index("\n", start)
    end = re.search(r"^### ", text[body:], re.M)
    return squashed(text[start : body + end.start()] if end else text[start:])


def command_section() -> str:
    """`docs/cli.md`'s `abk reconcile` section, up to the next heading."""
    text = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    start = text.index("### `abk reconcile")
    body = text.index("\n", start)
    end = re.search(r"^#{1,3} ", text[body:], re.M)
    return squashed(text[start : body + end.start()] if end else text[start:])


def assert_describes_the_pass(text: str, name: str) -> None:
    assert re.search(r"reconcile", text, re.I), f"{name} lacks the reconcile pass"
    assert re.search(
        r"merged.{0,300}(in.review|running)|(in.review|running).{0,300}merged", text
    ), f"{name} lacks the unit whose merge was never recorded"
    assert re.search(r"cache|snapshot", text, re.I), f"{name} lacks that the pass reads the cache"


def assert_describes_the_command(text: str, name: str) -> None:
    assert "abk reconcile" in text, name
    assert "--dry-run" in text, name
    assert "--accept" in text, name
    assert re.search(r"refus.{0,200}(open|closed|settling)", text, re.I), (
        f"{name} lacks what --accept refuses"
    )


def test_the_architecture_poller_section_describes_the_pass() -> None:
    text = poller_section()
    assert_describes_the_pass(text, "docs/architecture.md")
    assert "abk reconcile" in text


def test_the_cli_document_describes_the_command() -> None:
    text = command_section()
    assert_describes_the_command(text, "docs/cli.md")
    assert re.search(r"abk reconcile \[?UNIT", text)


@pytest.mark.parametrize("flag", ["--dry-run", "--accept"])
def test_the_cli_document_heading_shows_the_flags(flag: str) -> None:
    text = (ROOT / "docs" / "cli.md").read_text(encoding="utf-8")
    heading = next(line for line in text.splitlines() if line.startswith("### `abk reconcile"))
    assert flag in heading


def test_the_pipeline_skill_describes_the_pass_and_the_command() -> None:
    text = squashed(SKILL.read_text(encoding="utf-8"))
    assert_describes_the_pass(text, "abk-pipeline skill")
    assert_describes_the_command(text, "abk-pipeline skill")


def test_the_changelog_has_one_bullet_for_the_command() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("\n## ", 2)[1]
    assert len(re.findall(r"`abk reconcile`", unreleased)) == 1
