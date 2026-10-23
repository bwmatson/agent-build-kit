"""The skills, the documents and the changelog say what an e2e-test group holds."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
DOCS = ROOT / "docs"
AUTHORING = SKILLS / "abk-authoring" / "SKILL.md"
PIPELINE = SKILLS / "abk-pipeline" / "SKILL.md"


def squashed(text: str) -> str:
    """The text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(text.replace("`", "").split())


def squashed_file(path: Path) -> str:
    return squashed(path.read_text(encoding="utf-8"))


def section(path: Path, heading: str) -> str:
    """The squashed text from the heading line to the next heading of the same or a higher level."""
    text = path.read_text(encoding="utf-8")
    start = text.index(heading)
    level = len(heading) - len(heading.lstrip("#"))
    end = re.search(rf"\n#{{1,{level}}} ", text[start + 1 :])
    return squashed(text[start : start + 1 + end.start() if end else None])


def test_the_authoring_skill_names_the_stand_alone_unit_and_that_separate_is_not_needed() -> None:
    text = squashed_file(AUTHORING)
    assert re.search(r"e2e-test.{0,300}(unit of its own|stand-alone)", text, re.I)
    assert re.search(
        r"e2e-test.{0,400}(needs? no|no need for|not needed).{0,40}Separate:", text, re.I
    )


def test_the_authoring_skill_lists_what_an_e2e_group_holds_and_support() -> None:
    text = squashed_file(AUTHORING)
    assert re.search(r"e2e-test.{0,500}test(s)? (file|path|support|helper)", text, re.I)
    assert "Support:" in text
    assert re.search(r"Support:.{0,300}reason", text, re.I)


def test_the_authoring_skill_says_not_to_put_product_fixes_in_an_e2e_group() -> None:
    text = squashed_file(AUTHORING)
    assert re.search(r"do not put product fixes in an e2e group", text, re.I)


def test_the_authoring_skill_names_the_fix_change_and_the_group_written_first() -> None:
    text = squashed_file(AUTHORING)
    assert "fix-product-defect" in text
    assert re.search(
        r"fix-product-defect.{0,800}\[unit-test\]|\[unit-test\].{0,800}fix-product-defect", text
    )
    assert re.search(r"(knows|know) of the defect.{0,300}\[unit-test\]", text, re.I)


def test_the_authoring_skill_lists_e2e_test_among_the_groups_never_joined() -> None:
    text = squashed(section(AUTHORING, "## `Separate:` lines"))
    assert re.search(r"\[e2e-test\].{0,120}never joined|never joined.{0,200}\[e2e-test\]", text)


def test_the_authoring_skill_version_is_bumped() -> None:
    match = re.search(r"^version: (\d+)\.(\d+)\.(\d+)$", AUTHORING.read_text("utf-8"), re.M)
    assert match
    assert tuple(int(part) for part in match.groups()) > (1, 1, 0)


def test_the_architecture_document_names_the_join_rule_the_guard_and_the_defect_path() -> None:
    text = squashed_file(DOCS / "architecture.md")
    assert re.search(r"e2e-test.{0,300}(never joined|unit of its own)", text, re.I)
    assert re.search(r"checks.{0,300}(scope guard|guard).{0,300}product", text, re.I)
    assert re.search(r"product[- ]defect.{0,600}fix change|fix-product-defect", text, re.I)


def test_the_cli_document_names_the_product_path_warning_and_its_limits() -> None:
    text = section(DOCS / "cli.md", "### `abk tags [CHANGE] [--all]`")
    assert re.search(r"e2e-test.{0,400}product (code|path)", text, re.I)
    assert re.search(r"backtick", text, re.I)
    assert re.search(r"false positive", text, re.I)
    assert "Support:" in text


def test_the_unit_graph_shows_the_guard_at_the_top_of_checks() -> None:
    text = (DOCS / "unit-graph.md").read_text(encoding="utf-8")
    assert re.search(r"guard", text, re.I)
    edges = [line for line in text.splitlines() if "-->" in line and "guard" in line.lower()]
    assert any(re.search(r"\bchecks\b", line) for line in edges)


def test_the_pipeline_skill_has_a_paragraph_on_the_product_defect_wait() -> None:
    text = squashed_file(PIPELINE)
    assert re.search(r"product defect.{0,600}(wait|Needs)", text, re.I)
    assert "fix-product-defect" in text
    assert "failed units resumed when their wait ended" in text


def test_the_changelog_has_the_bullet_once_under_unreleased() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text.split("\n## ", 2)[1]
    assert unreleased.startswith("Unreleased")
    bullets = [b for b in re.split(r"\n\n(?=- )", unreleased) if "e2e-test" in b]
    matching = [b for b in bullets if re.search(r"product (code|defect|path)", b, re.I)]
    assert len(matching) == 1
    assert len(re.findall(r"stand-alone|unit of its own", unreleased, re.I)) >= 1
    assert text.count(matching[0]) == 1
