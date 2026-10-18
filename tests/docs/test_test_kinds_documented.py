"""The documents name the three test kinds and what each covers (spec: test-kind-names)."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = flat((ROOT / "docs" / "architecture.md").read_text())
TAGS = ("unit-test", "integration-test", "e2e-test")
TEXTS = {
    "README.md": (ROOT / "README.md").read_text(),
    "AGENTS.md": (ROOT / "AGENTS.md").read_text(),
    **{f"{name} (source)": skills.source(name) for name in skills.names()},
    **{f"{name} (installed)": skills.rendered(name) for name in skills.names()},
}


def test_the_architecture_names_all_three_tags() -> None:
    assert [t for t in TAGS if f"`{t}`" not in ARCHITECTURE] == []


def test_the_architecture_says_integration_test_covers_behaviour_across_modules_or_files() -> None:
    assert re.search(
        r"`integration-test`[^.]*behaviour across (several )?modules or files[^.]*"
        r"(ordinary suite|no live stack)",
        ARCHITECTURE,
    )


def test_the_architecture_says_integration_test_behaves_as_unit_test_in_every_other_way() -> None:
    assert re.search(r"`unit-test` in every other way", ARCHITECTURE)


def test_the_architecture_says_integration_test_is_not_the_pytest_marker_or_directory() -> None:
    assert re.search(r"not the[^.]*`integration` marker[^.]*`tests/integration/`", ARCHITECTURE)


def test_the_architecture_says_a_unit_of_several_groups_takes_the_widest_kind() -> None:
    assert re.search(r"several groups[^.]*widest", ARCHITECTURE)


def test_the_architecture_lists_the_kinds_from_narrowest_to_widest() -> None:
    positions = [ARCHITECTURE.index(f"`{tag}`") for tag in TAGS]

    assert positions == sorted(positions)


def test_each_top_level_document_and_skill_names_all_three_tags() -> None:
    missing = {where: [t for t in TAGS if t not in text] for where, text in TEXTS.items()}

    assert {where: tags for where, tags in missing.items() if tags} == {}
