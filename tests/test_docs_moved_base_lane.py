"""The documents and the `abk-pipeline` skill describe the moved-base run the restack lane makes."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md"
DOCUMENTS = (
    DOCS / "architecture.md",
    DOCS / "unit-graph.md",
    DOCS / "configuration.md",
    DOCS / "cli.md",
    SKILL,
)
IDS = [path.name if path != SKILL else "abk-pipeline-skill" for path in DOCUMENTS]


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDS)
def test_the_cause_of_a_handed_back_run_is_named(path: Path) -> None:
    assert "restack_handed_back" in squashed(path)


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDS)
def test_the_run_is_called_a_moved_base_run(path: Path) -> None:
    assert "moved-base run" in squashed(path)


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDS)
def test_the_lane_cap_is_said_to_bound_the_run(path: Path) -> None:
    text = squashed(path)
    assert re.search(r"lane's cap bounds the (moved-base )?run", text, re.I), (
        f"{path.name} does not say that the lane's cap bounds the run"
    )


@pytest.mark.parametrize("path", DOCUMENTS, ids=IDS)
def test_the_run_is_said_to_count_toward_occupancy_and_never_be_held_back(path: Path) -> None:
    text = squashed(path)
    assert re.search(r"run counts toward slot occupancy", text, re.I), (
        f"{path.name} does not say that the run counts toward slot occupancy"
    )
    assert re.search(r"never held back by the limit", text, re.I), (
        f"{path.name} does not say that the run is never held back by the limit"
    )


OLD_ACCOUNTS = (
    r"restack takes none of (these|the limits)",
    r"outside max_concurrent_stacks",
    r"beside the build workers",
    r"apart from the build workers",
    r"work after a move runs in a build worker",
)


def test_the_old_accounts_of_the_lane_are_gone() -> None:
    found = [
        f"{path.name}: {pattern}"
        for path in DOCUMENTS
        for pattern in OLD_ACCOUNTS
        if re.search(pattern, squashed(path), re.I)
    ]
    assert not found
