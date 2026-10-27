"""The documents, the runbook and the changelog say an in-repo installation's state is in the
planning home outside the repository, and how an existing one is moved (spec:
planning-state-external-checks)."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed, unreleased_bullets

DOCS = ROOT / "docs"
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
RUNBOOK = DOCS / "runbooks" / "move-state-out-of-the-repo.md"
# What an old document says of the store when it is committed: a table cell or a sentence.
COMMITTED = re.compile(
    r"units\.json[^\n]*\bCommit it\b"
    r"|units\.json[^.|\n]{0,60}\b(?:is|are|stays?) (?:committed|tracked)"
)


def read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def test_no_document_says_the_store_is_committed() -> None:
    paths = [
        *DOCS.glob("*.md"),
        *SKILLS.glob("*/SKILL.md"),
        DOCS / "runbooks" / "move-agent-build-kit-planning.md",
        ROOT / "CHANGELOG.md",
    ]

    saying = [
        str(p.relative_to(ROOT)) for p in paths if COMMITTED.search(p.read_text(encoding="utf-8"))
    ]

    assert saying == []


def test_the_architecture_and_configuration_documents_name_the_state_and_the_reports() -> None:
    architecture = squashed(read("docs", "architecture.md"))
    configuration = squashed(read("docs", "configuration.md"))

    for text in (architecture, configuration):
        assert "<planning home>/state" in text
        assert "planning.reports_dir" in text
    assert re.search(r"two hosts.{0,80}(unsupported|not supported)", configuration)


def test_the_runbook_holds_the_steps_in_order_and_a_rollback() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    places = [
        text.index(step) for step in ("install-timers --no-enable", "git rm -r runs/", "Rollback")
    ]

    assert places == sorted(places)
    assert re.search(r"^#+ Rollback", text, re.M)


def test_the_changelog_has_an_unreleased_entry_naming_the_planning_home() -> None:
    assert any("planning.home" in bullet and "state" in bullet for bullet in unreleased_bullets())
