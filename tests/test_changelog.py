"""The changelog keeps its form, so a unit's entry is checked before any review."""

from pathlib import Path

import pytest

from tests.changelog_form import changelog_problems

ROOT = Path(__file__).resolve().parents[1]

WELL_FORMED = """\
# Changelog

## Unreleased

- A new thing, described for someone using the tool and
  wrapped with a two-space continuation.

- Another thing, with its reason.

## 0.2.0 — 2026-10-01

- Released work.

## 0.1.0 — 2026-09-28

- First release.
"""


def test_a_well_formed_changelog_passes() -> None:
    assert changelog_problems(WELL_FORMED) == []


def test_the_changelog_in_this_repository_passes() -> None:
    assert changelog_problems((ROOT / "CHANGELOG.md").read_text()) == []


@pytest.mark.parametrize("marker", ["<<<<<<< HEAD", "=======", ">>>>>>> spec/feature/1"])
def test_a_conflict_marker_fails_naming_its_line(marker: str) -> None:
    text = WELL_FORMED.replace("- Another thing, with its reason.\n", f"{marker}\n- Another.\n")
    line = text.splitlines().index(marker) + 1

    problems = changelog_problems(text)

    assert any(f"line {line}" in problem for problem in problems)


def test_two_bullets_run_together_fail_naming_the_second() -> None:
    text = WELL_FORMED.replace(
        "\n- Another thing, with its reason.", "- Another thing, with its reason."
    )
    line = text.splitlines().index("- Another thing, with its reason.") + 1

    problems = changelog_problems(text)

    assert any(f"line {line}" in problem for problem in problems)


def test_a_duplicated_bullet_fails_naming_the_repeat() -> None:
    text = WELL_FORMED.replace(
        "- Another thing, with its reason.",
        "- A new thing, described for someone using the tool and wrapped\n"
        "  with a two-space continuation.",
    )
    line = (
        text.splitlines().index("- A new thing, described for someone using the tool and wrapped")
        + 1
    )

    problems = changelog_problems(text)

    assert any(f"line {line}" in problem for problem in problems)


def test_a_bullet_outside_any_section_fails_naming_its_line() -> None:
    text = WELL_FORMED.replace("## Unreleased\n", "- Stray.\n\n## Unreleased\n")
    line = text.splitlines().index("- Stray.") + 1

    problems = changelog_problems(text)

    assert any(f"line {line}" in problem for problem in problems)


@pytest.mark.parametrize(
    "headings",
    [
        ["## 0.2.0 — 2026-10-01", "## Unreleased", "## 0.1.0 — 2026-09-28"],
        ["## Unreleased", "## 0.1.0 — 2026-09-28", "## 0.2.0 — 2026-10-01"],
    ],
)
def test_headings_out_of_order_fail_naming_the_misplaced_heading(headings: list[str]) -> None:
    body = {
        "## Unreleased": "- A new thing.",
        "## 0.2.0 — 2026-10-01": "- Released work.",
        "## 0.1.0 — 2026-09-28": "- First release.",
    }
    text = "# Changelog\n\n" + "\n\n".join(f"{h}\n\n{body[h]}" for h in headings) + "\n"
    lines = text.splitlines()
    misplaced = {lines.index(headings[0]) + 1, lines.index(headings[1]) + 1}

    problems = changelog_problems(text)

    assert any(f"line {line}" in problem for problem in problems for line in misplaced)
