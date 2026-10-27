"""A change holding `tracker.yaml` still validates and archives through the real OpenSpec CLI
(spec: tracker-mapping). Needs node (npx) and, on the first run, the network."""

from __future__ import annotations

import shutil

import pytest

from agent_build_kit import openspec
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.tracker_file import (
    FILE_NAME,
    Synced,
    TrackerFile,
    read_tracker,
    write_tracker,
)
from tests.openspec_cli import require

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.usefixtures("openspec_cli"),
]


def test_validate_passes_and_archive_keeps_the_file(installation: Installation) -> None:
    folder = installation.changes_dir / "feature"
    delta = folder / "specs" / "marker"
    delta.mkdir(parents=True)
    (installation.specs_dir / "specs").mkdir(parents=True, exist_ok=True)
    (folder / "proposal.md").write_text("## Why\n\nA marker.\n\n## What Changes\n\n- Marker.\n")
    (folder / "tasks.md").write_text("## 1. [app] [unit-test] Marker\n\n- [ ] 1.1 Test: it\n")
    (delta / "spec.md").write_text(
        "## ADDED Requirements\n\n### Requirement: A marker exists\n\n"
        "The system SHALL have a marker.\n\n#### Scenario: it exists\n\n"
        "- **WHEN** asked\n- **THEN** it is there\n"
    )
    written = TrackerFile(kind="board", target="example-board", feature=Synced(id="100"))
    write_tracker(folder, written)

    require(openspec.run(["validate", "feature"], cwd=installation.root))
    require(openspec.run(["archive", "feature", "--yes"], cwd=installation.root))

    archived = [p for p in (installation.changes_dir / "archive").iterdir() if p.is_dir()]
    assert len(archived) == 1
    assert (archived[0] / FILE_NAME).is_file()
    assert read_tracker(archived[0]) == written
