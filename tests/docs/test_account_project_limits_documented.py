"""The documents and the two skills describe an account's `project_limits`: the same settings as
the top level, the caps that are counted for the account across its projects, and that the
account's `max_units_in_progress` replaces the project's value for its slot; the old key under an
account is documented as deprecated, and the changelog's unreleased section has one entry for it."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

BLOCK = "an account's `project_limits`"
ACROSS = "are counted for the account across its projects, beside each project's own cap"
REPLACES = "`max_units_in_progress` replaces the project's value for the account's slot"
CAPS = "`max_concurrent_stacks`, `max_concurrent_resolutions` and `emergency_extra`"
OLD_KEY = "`accounts.<label>.max_units_in_progress`"

DOCUMENTS = {
    "docs/configuration.md": (ROOT / "docs" / "configuration.md").read_text(encoding="utf-8"),
    "docs/architecture.md": (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"),
    "docs/designs/unit-graph.md": (ROOT / "docs" / "designs" / "unit-graph.md").read_text(
        encoding="utf-8"
    ),
    "docs/cli.md": (ROOT / "docs" / "cli.md").read_text(encoding="utf-8"),
    "docs/runbooks/landing-changes.md": (
        ROOT / "docs" / "runbooks" / "landing-changes.md"
    ).read_text(encoding="utf-8"),
    "docs/designs/worker-design.md": (ROOT / "docs" / "designs" / "worker-design.md").read_text(
        encoding="utf-8"
    ),
    "docs/claude-code-second-account.md": (
        ROOT / "docs" / "claude-code-second-account.md"
    ).read_text(encoding="utf-8"),
    "skill abk-config": skills.source("abk-config"),
    "skill abk-pipeline": skills.source("abk-pipeline"),
}
# The second-account how-to shows the block and not the caps.
SHOWS_ONLY_THE_BLOCK = {"docs/claude-code-second-account.md"}

# What a document said before the caps counted across an account's projects.
STALE = [
    "against that account's own `max_units_in_progress`",
    "against `runtimes.claude_code.accounts.<label>.max_units_in_progress`",
    "`max_concurrent_stacks` is always counted for each project, not for each account",
    "`max_concurrent_stacks` is counted for each project, not for each account",
    "accepts its own `max_units_in_progress` and `limits`",
]


def read(name: str) -> str:
    return flat(DOCUMENTS[name]).lower()


@pytest.mark.parametrize("name", DOCUMENTS)
def test_each_document_describes_an_accounts_project_limits(name: str) -> None:
    assert BLOCK in read(name)


@pytest.mark.parametrize("name", [n for n in DOCUMENTS if n not in SHOWS_ONLY_THE_BLOCK])
def test_each_document_says_which_caps_count_across_an_accounts_projects(name: str) -> None:
    assert ACROSS in read(name)
    assert REPLACES in read(name)


@pytest.mark.parametrize(
    "name", ["docs/configuration.md", "docs/architecture.md", "skill abk-config"]
)
def test_the_reference_names_the_three_account_caps(name: str) -> None:
    assert CAPS in read(name)


@pytest.mark.parametrize("name", DOCUMENTS)
def test_no_document_keeps_the_earlier_wording(name: str) -> None:
    text = read(name)
    for old in STALE:
        assert old.lower() not in text, (name, old)


@pytest.mark.parametrize("name", ["docs/configuration.md", "docs/cli.md", "skill abk-config"])
def test_the_old_account_key_is_documented_as_deprecated_and_moved_by_migrate(name: str) -> None:
    text = read(name)
    assert OLD_KEY in text
    assert "deprecated" in text
    assert "an account's `max_units_in_progress` into its `project_limits`" in text


def test_the_configuration_reference_shows_the_block_under_an_account() -> None:
    text = DOCUMENTS["docs/configuration.md"]

    assert re.search(r"accounts:\n\s+kit:\n(?:.*\n)*?\s+project_limits:[^\n]*\n", text)


def test_the_second_account_how_to_sets_the_slots_in_the_block() -> None:
    text = DOCUMENTS["docs/claude-code-second-account.md"]

    assert re.search(r"project_limits:[^\n]*\n\s+max_units_in_progress: 3", text)
    assert text.count("max_units_in_progress: 3") == 1


def test_the_runbook_describes_the_account_with_its_project_limits() -> None:
    text = read("docs/runbooks/landing-changes.md")

    assert "`project_limits` and its `max_units_in_progress`" not in text
    assert "that plan's `usage_limits` and its `project_limits`" in text


def unreleased_bullets() -> list[str]:
    unreleased = CHANGELOG.split("\n## ")[1]
    return [flat(b) for b in re.split(r"\n\s*\n", unreleased) if b.lstrip().startswith("- ")]


def test_the_changelog_has_one_entry_for_the_account_limits() -> None:
    found = [b for b in unreleased_bullets() if "an account's `project_limits`" in b.lower()]

    assert len(found) == 1
    entry = found[0]
    assert "`max_units_in_progress`" in entry
    assert "`abk config --migrate`" in entry
    assert "abk.local.yaml" in entry
    assert "dropped one release after" in entry
