"""The architecture document describes the work tracker; the hand-off document drops "interim"."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def tracker_section() -> str:
    """The body of the first `docs/architecture.md` section whose heading contains "tracker"."""
    lines = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8").splitlines()
    start = next(
        (
            index
            for index, line in enumerate(lines)
            if re.match(r"#+\s", line) and "tracker" in line.lower()
        ),
        None,
    )
    assert start is not None, "docs/architecture.md has no heading containing 'tracker'"
    level = len(lines[start]) - len(lines[start].lstrip("#"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        heading = re.match(r"(#+)\s", line)
        if heading and len(heading.group(1)) <= level:
            break
        body.append(line)
    return "\n".join(body)


def test_the_architecture_document_has_a_work_tracker_section_naming_its_parts() -> None:
    section = tracker_section()
    lowered = section.lower()
    missing = [
        term for term in ("reconciler", "wanted board", "manual parent") if term not in lowered
    ]
    if "Epic" not in section:
        missing.append("Epic")
    assert missing == [], f"the work-tracker section does not name: {missing}"


def test_the_hand_off_document_does_not_call_the_hold_interim() -> None:
    text = (ROOT / "docs" / "hand-off.md").read_text(encoding="utf-8")
    assert "interim" not in text.lower()
