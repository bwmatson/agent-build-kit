"""The documents describe the red check's selection by id and its fallback."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


def squashed(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


def test_the_architecture_document_places_a_new_case_in_the_existing_file() -> None:
    text = squashed(DOCS / "architecture.md")

    assert re.search(r"new case.{0,80}existing test file", text, re.I)
    assert "New tests go in files in which every test fails" not in text


def test_the_architecture_document_names_the_fallback_to_whole_files() -> None:
    text = squashed(DOCS / "architecture.md")

    assert re.search(r"red check.{0,900}(not collect|cannot select|no id).{0,200}whole", text, re.I)


def test_the_architecture_document_does_not_claim_selection_reaches_integration_tests() -> None:
    text = squashed(DOCS / "architecture.md")

    assert re.search(r"by id.{0,400}integration.{0,100}(not|later change)", text, re.I)


def test_the_profiles_document_does_not_claim_selection_reaches_integration_tests() -> None:
    text = squashed(DOCS / "toolchain-profiles.md")

    assert re.search(r"red_command.{0,800}integration.{0,100}(not|later change)", text, re.I)
