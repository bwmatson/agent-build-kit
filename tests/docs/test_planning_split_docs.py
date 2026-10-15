"""The command reference and the pipeline skill describe `abk planning split`."""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "docs" / "cli.md"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md"
FLAGS = ("--repo", "--project", "--to", "--allow-mixed", "--spec", "--scrub", "--remove", "--apply")


def squashed(path: Path) -> str:
    return " ".join(path.read_text().split())


def entry() -> str:
    """The command reference from the first mention of the command to the next heading."""
    text = CLI.read_text()
    assert "abk planning split" in text
    start = text.index("abk planning split")
    following = re.search(r"^#{1,3} ", text[start:], re.M)
    return " ".join(text[start : start + following.start()].split()) if following else text[start:]


@pytest.mark.parametrize("flag", FLAGS)
def test_the_reference_names_each_flag(flag):
    assert flag in entry()


def test_the_reference_gives_the_exit_codes_and_the_default():
    text = entry()
    assert re.search(r"exit(s| code)", text, re.I)
    assert "dry run" in text.lower()
    assert all(code in text for code in ("0", "1", "2"))


def test_the_skill_names_the_command_and_the_dry_run_first():
    text = squashed(SKILL)
    assert "abk planning split" in text
    assert re.search(r"dry run[^.]*first|first[^.]*dry run", text, re.I)
