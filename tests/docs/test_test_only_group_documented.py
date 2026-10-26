"""The documents, the skills and the changelog describe test-only groups."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
DOCS = ROOT / "docs"


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


def test_the_architecture_document_names_a_test_only_group_and_its_lone_commit() -> None:
    text = squashed_file(DOCS / "architecture.md")
    assert re.search(r"test-only group", text, re.I)
    assert re.search(
        r"test-only.{0,600}single .{0,20}test: commit|test-only.{0,600}lone .{0,20}test: commit",
        text,
        re.I,
    )
    assert re.search(
        r"test-only.{0,800}implement step.{0,100}(skip|past|no )|skips? the implement step",
        text,
        re.I,
    )


def test_the_architecture_document_says_how_the_pair_count_and_the_gate_treat_it() -> None:
    text = squashed_file(DOCS / "architecture.md")
    assert re.search(r"test-only.{0,1500}pair count|pair count.{0,800}test-only", text, re.I)
    assert re.search(
        r"test-only.{0,1500}no red (run|command)|no red (run|command).{0,400}test-only", text, re.I
    )
    assert re.search(r"gate.{0,600}exception|exception.{0,600}gate", text, re.I)


def test_the_unit_graph_shows_the_edge_from_stub_checks_past_implement() -> None:
    text = (DOCS / "designs/unit-graph.md").read_text(encoding="utf-8")
    edges = [line for line in text.splitlines() if "stub_checks" in line and "-->" in line]
    assert any(
        re.search(r"stub_checks\s*-->\|[^|]*test-only[^|]*\|\s*(tests|checks)\b", line, re.I)
        for line in edges
    )


def test_the_unit_graph_rows_for_stub_checks_and_implement_name_test_only_groups() -> None:
    text = squashed_file(DOCS / "designs/unit-graph.md")
    assert re.search(r"stub_checks.{0,1200}test-only", text, re.I)
    assert re.search(r"implement.{0,1200}test-only", text, re.I)


def test_the_cli_document_says_the_gate_reads_the_groups_from_the_unit_trailer() -> None:
    text = section(DOCS / "cli.md", "### `abk gate")
    assert "Unit:" in text
    assert re.search(r"Unit:.{0,300}groups|groups.{0,300}Unit:", text, re.I)
    assert re.search(r"test-only", text, re.I)


def test_the_authoring_skill_says_an_e2e_test_group_is_one_test_commit() -> None:
    text = squashed_file(SKILLS / "abk-authoring" / "SKILL.md")
    assert re.search(
        r"\[e2e-test\].{0,500}\[acceptance\].{0,500}(one|single|lone) test: commit", text, re.I
    )
    assert re.search(
        r"(unit-test|integration-test).{0,400}still needs? its implementation", text, re.I
    )


def test_the_pipeline_skill_stub_check_paragraph_names_the_lone_commit() -> None:
    text = section(SKILLS / "abk-pipeline" / "SKILL.md", "### Stopped in the stub check loop")
    assert re.search(r"test-only", text, re.I)
    assert re.search(r"(lone|single|one) test: commit", text, re.I)


def test_the_push_gate_paragraph_describes_the_test_only_exception() -> None:
    text = (DOCS / "architecture.md").read_text(encoding="utf-8")
    start = text.index("**The push gate**")
    paragraph = squashed(text[start : text.index("\n\n", start)])
    assert re.search(r"test-only.{0,300}no red run", paragraph, re.I)
    assert re.search(r"only of test-only groups needs no implementation commit", paragraph, re.I)
