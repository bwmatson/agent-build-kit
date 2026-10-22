"""The documents and the changelog say a built group is recorded with an empty pair."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed, unreleased_bullets

DOCS = ROOT / "docs"


def says_empty_marked_pair_after_passing_tests(text: str) -> bool:
    return bool(
        re.search(r"nothing to commit", text, re.I)
        and re.search(r"empty.{0,80}pair", text, re.I)
        and re.search(r"Already-built: yes", text)
        and re.search(r"unit tests? pass", text, re.I)
    )


def test_the_architecture_document_says_a_group_with_nothing_to_commit_is_recorded() -> None:
    text = squashed((DOCS / "architecture.md").read_text(encoding="utf-8"))
    start = text.index("Stubbed build, per group.")
    paragraph = text[start : text.index("Test-only groups.", start)]
    assert says_empty_marked_pair_after_passing_tests(paragraph)
    assert re.search(r"feat: .{0,40}(body|commit).{0,120}account", paragraph, re.I)
    assert re.search(
        r"test-only.{0,200}(lone|single|one) empty .{0,20}test: commit", paragraph, re.I
    )
    assert re.search(
        r"forgotten implementation.{0,200}stops|stops.{0,200}forgotten implementation",
        paragraph,
        re.I,
    )


def test_the_push_gate_paragraph_says_a_restack_keeps_the_pair_and_the_squash_drops_it() -> None:
    text = (DOCS / "architecture.md").read_text(encoding="utf-8")
    start = text.index("**The push gate**")
    paragraph = squashed(text[start : text.index("\n\n", start)])
    assert re.search(r"Already-built", paragraph)
    assert re.search(r"restack.{0,100}keeps", paragraph, re.I)
    assert re.search(r"squash.{0,100}drops", paragraph, re.I)


def test_the_unit_graph_implement_row_says_a_built_group_is_recorded() -> None:
    text = (DOCS / "unit-graph.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| `implement` |"))
    assert says_empty_marked_pair_after_passing_tests(squashed(row))


def test_the_unit_graph_stub_checks_row_says_a_test_only_group_already_built_is_recorded() -> None:
    text = (DOCS / "unit-graph.md").read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| `stub_checks` |"))
    squashed_row = squashed(row)
    assert re.search(
        r"test-only.{0,300}empty .{0,20}test: commit.{0,100}Already-built", squashed_row, re.I
    )
    assert not re.search(r"test-only.{0,300}empty pair", squashed_row, re.I)


def test_the_changelog_holds_one_bullet_for_the_recorded_built_group() -> None:
    matching = [
        b
        for b in unreleased_bullets()
        if re.search(r"nothing to commit", b) and re.search(r"empty.{0,80}pair", b)
    ]
    assert len(matching) == 1
