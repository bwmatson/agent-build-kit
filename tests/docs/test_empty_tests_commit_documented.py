"""The documents and the changelog say a group with no new tests gets an empty tests commit."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed, unreleased_bullets

DOCS = ROOT / "docs"


def stubbed_paragraph() -> str:
    text = squashed((DOCS / "architecture.md").read_text(encoding="utf-8"))
    start = text.index("Stubbed build, per group.")
    return text[start : text.index("Test-only groups.", start)]


def push_gate_paragraph() -> str:
    text = squashed((DOCS / "architecture.md").read_text(encoding="utf-8"))
    start = text.index("The push gate (")
    return text[start : start + 4000]


def unit_graph_row(name: str) -> str:
    text = (DOCS / "unit-graph.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith(f"| `{name}` |"))
    return squashed(row)


def test_the_stubbed_build_paragraph_says_a_group_with_no_new_tests_gets_an_empty_test_commit() -> (
    None
):
    paragraph = stubbed_paragraph()
    assert re.search(
        r"no new tests.{0,300}empty.{0,40}test: commit"
        r"|empty.{0,40}test: commit.{0,300}no new tests",
        paragraph,
        re.I,
    )
    assert re.search(r"Already-built: yes", paragraph)


def test_the_stubbed_build_paragraph_says_passing_real_tests_get_an_empty_feat_commit() -> None:
    paragraph = stubbed_paragraph()
    assert re.search(
        r"already pass.{0,300}empty.{0,40}feat: commit.{0,300}whole-repository unit tests"
        r"|already pass.{0,300}whole-repository unit tests.{0,300}empty.{0,40}feat: commit",
        paragraph,
        re.I,
    )


def test_the_stubbed_build_paragraph_says_a_lone_feat_commit_is_named_in_the_stop() -> None:
    paragraph = stubbed_paragraph()
    assert re.search(
        r"feat: commit.{0,200}no test: commit before it.{0,200}(named|naming|names)"
        r"|(named|naming|names).{0,200}feat: commit.{0,200}no test: commit before it",
        paragraph,
        re.I,
    )


def test_the_push_gate_paragraph_says_it_accepts_an_empty_test_before_a_real_feat() -> None:
    paragraph = push_gate_paragraph()
    assert re.search(
        r"accepts? an empty.{0,60}test: commit.{0,80}real feat: commit", paragraph, re.I
    )
    assert re.search(r"allow-empty", paragraph)


def test_the_unit_graph_stub_checks_row_says_an_empty_test_commit_is_made() -> None:
    row = unit_graph_row("stub_checks")
    assert re.search(r"no new tests.{0,300}empty.{0,40}test: commit", row, re.I)


def test_the_unit_graph_implement_row_says_the_pair_is_completed() -> None:
    row = unit_graph_row("implement")
    assert re.search(r"empty.{0,40}feat: commit.{0,300}whole-repository unit tests", row, re.I)


def test_the_changelog_holds_the_empty_tests_commit_bullet_once() -> None:
    matching = [
        b
        for b in unreleased_bullets()
        if re.search(r"no new tests", b) and re.search(r"empty .{0,20}test: commit", b)
    ]
    assert len(matching) == 1
