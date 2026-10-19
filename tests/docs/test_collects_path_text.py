"""The documents and the changelog say the own-test selection names only collected files."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def squashed(text: str) -> str:
    """`text` on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(text.replace("`", "").split())


def section(path: Path, heading: str) -> str:
    """The `## ` section of `path` that begins with `heading`, squashed."""
    text = path.read_text(encoding="utf-8")
    start = text.index(f"## {heading}")
    end = text.find("\n## ", start + 1)
    return squashed(text[start : end if end != -1 else None])


def test_the_profile_document_lists_the_predicate_in_its_table_and_both_profile_sections() -> None:
    path = DOCS / "toolchain-profiles.md"
    table = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("|")]
    assert any("collects_path" in line for line in table)
    assert "collects_path" in section(path, "`python-uv`")
    assert "collects_path" in section(path, "`node-npm`")


def test_the_python_section_says_helpers_and_conftest_are_not_collected() -> None:
    text = section(DOCS / "toolchain-profiles.md", "`python-uv`")
    assert re.search(r"collects_path.{0,300}test_\*\.py", text)
    assert re.search(r"conftest", text.split("collects_path", 1)[1])


def test_the_architecture_document_names_the_stated_limit_and_the_skip() -> None:
    text = squashed((DOCS / "architecture.md").read_text(encoding="utf-8"))
    narrowing = text[text.index("narrowed to its own tests") :][:2500]
    assert re.search(r"collect", narrowing, re.I)
    assert re.search(r"conftest", narrowing)
    assert re.search(r"python_files", narrowing)
    assert re.search(r"testpaths", narrowing)
    assert re.search(r"only such files|only files .{0,40}not collected", narrowing, re.I)


def test_the_changelog_has_the_bullet_once_under_unreleased() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text[text.index("## Unreleased") :]
    unreleased = unreleased[: unreleased.find("\n## ", 1)]
    bullets = [
        squashed(bullet)
        for bullet in re.split(r"\n\n(?=- )", unreleased)
        if re.search(r"own tests?|own-test", bullet) and "collect" in bullet
    ]
    assert len(bullets) == 1
    assert re.search(r"helper|conftest", bullets[0])
