"""The documents and skills describe the two kinds of `Needs:` edge, the reasons and the waits."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
AUTHORING = SKILLS / "abk-authoring" / "SKILL.md"
PIPELINE = SKILLS / "abk-pipeline" / "SKILL.md"
GUIDANCE = (AUTHORING, PIPELINE, DOCS / "architecture.md")
GUIDANCE_IDS = ["abk-authoring", "abk-pipeline", "architecture.md"]
KIT_CODE = re.compile(
    r"\bthe kit's own (tick|requeue|plan|graph|build)\b|\bthis repo's own (tick|requeue)\b", re.I
)
INSTALLATION_WORDS = re.compile(r"\binstallation's own\b|\bour installation\b", re.I)


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


def test_architecture_describes_the_kinds_the_reasons_and_the_loaded_code_test() -> None:
    text = squashed(DOCS / "architecture.md")
    assert not re.search(r"merged.{0,80}deprecated|deprecated.{0,80}merged", text, re.I)
    assert re.search(r"merge edge", text, re.I)
    assert re.search(r"review edge|kind .{0,20}review", text, re.I)
    assert re.search(r"crosses repositories|cross-repo.{0,80}always", text, re.I)
    assert re.search(r"merge_needs", text)
    assert re.search(r"tick\.json", text)
    assert re.search(r"loaded code|merge is loaded|loads? the merge", text, re.I)
    assert re.search(r"failed unit.{0,200}(waits|waiting)", text, re.I)


def test_architecture_shows_the_flake_and_pre_existing_paths_as_plain_lines() -> None:
    text = squashed(DOCS / "architecture.md")
    assert "Needs: <change> group 1 merged" not in text
    assert "group 1 merged — failing test" not in text
    assert re.search(r"Needs: <change> group 1 line", text) or re.search(
        r"plain Needs:.{0,200}(flake|fix)", text, re.I
    )


def test_architecture_says_when_to_write_merged() -> None:
    text = squashed(DOCS / "architecture.md")
    assert re.search(r"(write|use) merged.{0,300}(only|when)", text, re.I)
    assert re.search(r"merged.{0,300}(shared|run|executes).{0,200}(code|tick)", text, re.I)


def test_the_unit_graph_document_names_the_edge_kinds_in_its_row_and_legend() -> None:
    text = squashed(DOCS / "unit-graph.md")
    assert "needs, merge" in text
    assert re.search(r"merge_needs", text)
    assert not re.search(r"merged.{0,80}deprecated", text, re.I)
    assert re.search(r"legend.{0,400}needs, merge|needs, merge.{0,400}legend", text, re.I)


def test_the_cli_document_words_the_three_waits_and_the_wait_end_rule() -> None:
    text = squashed(DOCS / "cli.md")
    assert re.search(r"waiting for <change> group <n> to merge", text)
    assert re.search(r"waiting for the next tick to load <change> group <n>'s merge", text)
    assert re.search(r"waiting for the kit checkout to include <change> group <n>'s merge", text)
    assert re.search(r"merge.{0,200}next tick|next tick.{0,200}merge", text, re.I)


def test_the_cli_document_says_a_requeue_of_a_needs_not_yet_merged_waits() -> None:
    text = squashed(DOCS / "cli.md")
    assert re.search(r"abk requeue.{0,600}(merge is loaded|loaded)", text, re.I)
    assert re.search(r"its wait ended.{0,200}loaded by tick", text, re.I)


def test_the_authoring_skill_gives_the_generic_rule_and_the_cross_repo_reading() -> None:
    text = squashed(AUTHORING)
    assert not re.search(r"merged.{0,80}deprecat|deprecat.{0,80}merged", text, re.I)
    assert re.search(r"plain Needs:.{0,200}another repository.{0,200}merge", text, re.I)
    assert re.search(r"merged.{0,400}(shared|loaded|runs? the|executes)", text, re.I)
    assert re.search(r"needs no merged", text, re.I)


def test_the_authoring_skill_has_three_example_needs_lines() -> None:
    text = AUTHORING.read_text(encoding="utf-8")
    lines = [
        line for line in text.splitlines() if re.search(r"Needs: [\w<>-]+ group [\w<>]+", line)
    ]
    assert len(lines) >= 3
    assert any(" merged " in line for line in lines)
    assert any(" merged" not in line for line in lines)


def test_the_pipeline_skill_names_the_three_waits_and_what_to_do() -> None:
    text = squashed(PIPELINE)
    assert re.search(r"waiting for <change> group <n> to merge", text)
    assert re.search(r"waiting for the next tick to load", text)
    assert re.search(r"waiting for the kit checkout to include", text)
    assert re.search(r"kit checkout.{0,300}(pull|fetch|update)", text, re.I)


def test_the_pipeline_skill_names_the_merge_kind_and_the_edge_labels() -> None:
    text = squashed(PIPELINE)
    assert "needs, merge" in text
    assert re.search(r"merge_needs|merge edge|merge dependency", text, re.I)


@pytest.mark.parametrize("path", GUIDANCE, ids=GUIDANCE_IDS)
def test_the_generic_guidance_is_about_any_installation_and_not_the_kits_own_code(
    path: Path,
) -> None:
    text = squashed(path)
    assert re.search(r"merge edge|merge dependency|merge kind", text, re.I)
    assert not KIT_CODE.search(text)
    assert not INSTALLATION_WORDS.search(text)


def test_the_changelog_has_one_bullet_for_the_kinds_of_edge() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text.split("\n## ", 2)[1]
    bullets = [b for b in re.split(r"\n\n(?=- )", unreleased) if "Needs:" in b and "merge" in b]
    assert len(bullets) == 1
    bullet = " ".join(bullets[0].split())
    assert re.search(r"when to (write|use) .{0,20}merged|merged.{0,80}(only|when)", bullet, re.I)
    assert not re.search(r"deprecated", bullet, re.I)
